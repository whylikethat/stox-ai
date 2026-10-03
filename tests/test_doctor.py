from datetime import date
from urllib.parse import quote
import pandas as pd
import pytest
from stox.doctor import sip_preflight, doctor
from stox.providers.alpaca import Alpaca
from stox.providers.fred import FRED
from stox.providers.http import HTTP, ProviderError


class CapturedHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response(kwargs['params']) if callable(self.response) else self.response


def bar(day):
    return {'t':pd.Timestamp(day).tz_localize('America/New_York').isoformat(),
            'o':500, 'h':502, 'l':499, 'c':501, 'v':1000000}


@pytest.mark.parametrize('now,expected', [
    ('2026-10-03T16:00:00Z','2026-10-02'),  # Saturday
    ('2026-10-03T04:05:00Z','2026-10-01'),  # within 16m of Friday's day end
    ('2026-10-02T15:00:00Z','2026-10-01'),  # regular market hours
    ('2026-10-02T20:00:00Z','2026-10-01'),  # exact close
    ('2026-10-02T20:01:00Z','2026-10-01'),  # immediately after close
    ('2026-10-05T12:00:00Z','2026-10-02'),  # Monday premarket
    ('2025-07-04T16:00:00Z','2025-07-03'),  # holiday, following early close
    ('2025-07-03T17:01:00Z','2025-07-02'),  # immediately after early close
    ('2025-03-10T14:00:00Z','2025-03-07'),  # DST boundary
])
def test_sip_doctor_safe_daily_window(calendar, now, expected):
    def response(params):
        assert params['feed']=='sip'
        assert params['timeframe']=='1Day'
        assert params['symbols']=='SPY'
        assert pd.Timestamp(params['end']) <= pd.Timestamp(now)-pd.Timedelta(minutes=16)
        stamp=pd.Timestamp(bar(expected)['t'])
        # Provider filters daily bars by their midnight timestamp. Old 09:30 start failed this.
        assert pd.Timestamp(params['start']) <= stamp <= pd.Timestamp(params['end'])
        assert pd.Timestamp(params['start']).tz_convert('America/New_York').hour==0
        return {'bars':{'SPY':[bar(expected)]},'next_page_token':None}
    http=CapturedHTTP(response)
    api=Alpaca({'ALPACA_API_KEY':'key-canary','ALPACA_API_SECRET':'secret-canary'},http)
    assert expected in sip_preflight(api,calendar,now)
    assert len(http.calls)==1


def test_production_freshness_guard_does_not_block_doctor(calendar):
    with pytest.raises(ValueError):
        calendar.sip_end('2026-10-02T20:01:00Z')
    sessions,start,end=calendar.historical_sip_window('2026-10-02T20:01:00Z')
    assert sessions[-1]=='2026-10-01'
    assert pd.Timestamp(end)<pd.Timestamp('2026-10-02T19:45:00Z')


@pytest.mark.parametrize('rows', [[],[bar('2026-10-05')],[dict(bar('2026-10-02'),c=float('nan'))],
                                  [dict(bar('2026-10-02'),h=float('inf'))],[{'t':'bad'}]])
def test_sip_rejects_empty_future_or_invalid_rows(calendar,rows):
    api=Alpaca({'ALPACA_API_KEY':'key','ALPACA_API_SECRET':'secret'},CapturedHTTP({'bars':{'SPY':rows}}))
    with pytest.raises(ProviderError,match='HTTP 200; no valid completed SPY daily bar') as exc:
        sip_preflight(api,calendar,'2026-10-03T16:00:00Z')
    assert 'returned_rows=' in str(exc.value)
    assert 'timeframe=1Day' in str(exc.value)


def observation(value='4.1'):
    return {'date':'2026-09-25','value':value,'realtime_start':'2026-09-26','realtime_end':'2026-09-26'}


def test_fred_simple_dgs10_observation():
    http=CapturedHTTP({'observations':[observation('.'),observation()]})
    assert FRED('configured-key',http).preflight()=='DGS10 2026-09-25: 4.1'
    params=http.calls[0][1]['params']
    assert params=={'series_id':'DGS10','api_key':'configured-key','file_type':'json','sort_order':'desc','limit':10}


@pytest.mark.parametrize('rows', [[],[observation('.')],[observation('NaN')],[observation('inf')],[{'date':'bad','value':'4.1'}]])
def test_fred_requires_actual_numeric_observation(rows):
    with pytest.raises(ProviderError,match='no valid DGS10 observation'):
        FRED('key',CapturedHTTP({'observations':rows})).preflight()


def test_optional_vintage_uses_single_valid_asof_date():
    http=CapturedHTTP({'observations':[observation()]})
    assert 'as of 2026-09-26' in FRED('key',http).preflight('2026-09-26')
    params=http.calls[0][1]['params']
    assert params['realtime_start']==params['realtime_end']=='2026-09-26'
    assert params['output_type']==1
    assert 'vintage_dates' not in params
    assert 'observation_start' not in params
    with pytest.raises(ProviderError,match='no valid DGS10 observation'):
        FRED('key',http).preflight('2026-09-27')


class Response:
    headers={}
    def __init__(self,status,payload=None,text=''):
        self.status_code,self.payload,self.text=status,payload,text
    def json(self):
        if self.payload is None:
            raise ValueError('not JSON')
        return self.payload


class Session:
    def __init__(self,response): self.response=response
    def get(self,*args,**kwargs): return self.response


def test_fred_http400_error_retains_message_redacts_key():
    key='private+fred/key'
    response=Response(400,{'error_code':400,'error_message':f'Bad Request. Variable realtime_start is invalid; api_key={quote(key,safe="")}'} )
    http=HTTP(Session(response),sleep=lambda _:None)
    with pytest.raises(ProviderError) as exc:
        FRED(key,http).preflight()
    message=str(exc.value)
    assert 'HTTP 400' in message and 'Variable realtime_start is invalid' in message
    assert key not in message and quote(key,safe='') not in message
    assert '[REDACTED]' in message


def test_sip_restriction_response_redacts_headers(calendar):
    key,secret='private-api-key','private-api-secret'
    response=Response(403,{'message':f'subscription does not permit querying recent SIP data; {key} {secret}'})
    api=Alpaca({'ALPACA_API_KEY':key,'ALPACA_API_SECRET':secret},HTTP(Session(response),sleep=lambda _:None))
    with pytest.raises(ProviderError) as exc:
        sip_preflight(api,calendar,'2026-10-02T20:01:00Z')
    assert 'HTTP 403' in str(exc.value)
    assert 'recent SIP data' in str(exc.value)
    assert key not in str(exc.value) and secret not in str(exc.value)


def test_non_json_error_is_sanitized_and_bounded():
    http=HTTP(Session(Response(400,text='Invalid parameter\napi_key=private-key&limit=bad '+ 'x'*1500)),sleep=lambda _:None)
    with pytest.raises(ProviderError) as exc:
        http.get('https://example.test?api_key=private-key')
    assert 'Invalid parameter' in str(exc.value)
    assert 'private-key' not in str(exc.value)
    assert '\n' not in str(exc.value)
    assert len(str(exc.value))<1050


def test_doctor_fred_pass_independent_of_vintage_failure(cfg,monkeypatch):
    import stox.doctor as module
    class FakeAlpaca:
        def __init__(self,*args): pass
        def assets(self): return [1]
        def news(self,*args): yield [1]
        def actions(self,*args): yield [1]
    class FakeSEC:
        def __init__(self,*args): pass
        def mappings(self): return {'SPY':1}
    class FakeFRED:
        calls=[]
        def __init__(self,*args): pass
        def preflight(self,vintage=None):
            self.calls.append(vintage)
            if vintage:
                raise ProviderError('Vintage-specific failure')
            return 'DGS10 2026-09-25: 4.1'
    monkeypatch.setattr(module,'Alpaca',FakeAlpaca)
    monkeypatch.setattr(module,'SEC',FakeSEC)
    monkeypatch.setattr(module,'FRED',FakeFRED)
    monkeypatch.setattr(module,'sip_preflight',lambda *args:'SPY completed daily SIP bar')
    monkeypatch.setattr(module,'utc',lambda:pd.Timestamp('2026-10-03T16:00:00Z'))
    checks={r['check']:r for r in doctor(cfg,live=True,vintages=True)}
    assert checks['FRED DGS10']['status']=='PASS'
    assert checks['ALFRED vintage DGS10']['status']=='WARN'
    assert FakeFRED.calls==[None,'2026-09-26']
    FakeFRED.calls.clear()
    checks={r['check']:r for r in doctor(cfg,live=True)}
    assert 'ALFRED vintage DGS10' not in checks
    assert FakeFRED.calls==[None]
