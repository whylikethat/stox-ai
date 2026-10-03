from __future__ import annotations
import importlib.metadata
import pandas as pd
import math
from .calendar import MarketCalendar,utc
from .storage import Store
from .security import MarketDataSymbol
from .providers.alpaca import Alpaca, parse_bar
from .providers.http import ProviderError
from .providers.sec import SEC
from .providers.fred import FRED
from .providers.alpha import AlphaVantage


def sip_preflight(alpaca, calendar, now):
    now = utc(now)
    sessions, start, end = calendar.historical_sip_window(now)
    pages = returned = invalid = 0
    for page in alpaca.bars([MarketDataSymbol('SPY','preflight:SPY','known_preflight')], start, end):
        pages += 1
        for raw in page.get('SPY', []) or []:
            returned += 1
            try:
                bar = parse_bar('SPY', raw, calendar, now.isoformat())
                stamp = utc(raw['t'])
                if (bar['session'] not in sessions or not utc(start) <= stamp <= utc(end)
                        or calendar.close(bar['session']) > now - pd.Timedelta(minutes=16)
                        or not all(math.isfinite(bar[k]) and bar[k] > 0 for k in ('open','high','low','close','volume'))):
                    raise ValueError('Not a valid completed bar')
                return f'SPY completed daily SIP bar: {bar["session"]}; historical window {start} to {end}'
            except (KeyError, TypeError, ValueError, ProviderError):
                invalid += 1
    # Counts and the explicit request window describe the successful-but-empty/invalid response;
    # never echo arbitrary bar values that could contain provider-supplied sensitive text.
    raise ProviderError(f'Alpaca SIP: HTTP 200; no valid completed SPY daily bar; '
                        f'pages={pages}, returned_rows={returned}, invalid_rows={invalid}; '
                        f'feed=sip timeframe=1Day start={start} end={end}')


def doctor(cfg,live=False,vintages=False):
    cfg.initialize()
    store=Store(cfg.root)
    checks=[]
    def check(name,action,core=True):
        try:
            detail=action()
            checks.append({'check':name,'status':'PASS','detail':str(detail)})
        except Exception as exc:
            checks.append({'check':name,'status':'FAIL' if core else 'WARN','detail':str(exc)})
    check('database',lambda:store.db.execute('PRAGMA integrity_check').fetchone()[0])
    check('storage',lambda:store.storage_check(cfg.soft_storage_gb,cfg.hard_storage_gb))
    for package in ('numpy','pandas','scikit-learn','pyarrow','duckdb','exchange-calendars'):
        check(package,lambda p=package:importlib.metadata.version(p))
    if live:
        cal=MarketCalendar()
        now=utc()
        check('Alpaca credentials/assets',lambda:len(Alpaca(cfg.secrets).assets()))
        check('Alpaca historical SIP',lambda:sip_preflight(Alpaca(cfg.secrets),cal,now))
        check('Alpaca news',lambda:len(next(Alpaca(cfg.secrets).news((utc()-pd.Timedelta(days=3)).isoformat(),utc().isoformat()))),False)
        check('Alpaca corporate actions',lambda:len(next(Alpaca(cfg.secrets).actions((utc()-pd.Timedelta(days=7)).isoformat(),utc().isoformat()))))
        check('SEC',lambda:len(SEC(cfg.secrets.get('SEC_USER_AGENT')).mappings()),False)
        check('FRED DGS10',lambda:FRED(cfg.secrets.get('FRED_API_KEY')).preflight(),False)
        if vintages:
            vintage=(now-pd.Timedelta(days=7)).date().isoformat()
            check('ALFRED vintage DGS10',lambda:FRED(cfg.secrets.get('FRED_API_KEY')).preflight(vintage),False)
        if cfg.secrets.get('ALPHAVANTAGE_API_KEY'):
            check('Alpha Vantage',lambda:len(AlphaVantage(cfg.secrets['ALPHAVANTAGE_API_KEY'],store,cfg.av_daily_budget).earnings()),False)
    else:
        checks.append({'check':'providers','status':'WARN','detail':'Not contacted. Use stox doctor --live explicitly.'})
    store.close()
    return checks
