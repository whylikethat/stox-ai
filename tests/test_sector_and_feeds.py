import numpy as np
import pandas as pd
from types import SimpleNamespace


def test_sector_proxy_is_causal(store,cfg,calendar,monkeypatch):
    from stox.features import build_features
    from stox.security import SecurityMaster
    days=calendar.sessions('2023-01-03','2024-12-31')
    x=np.arange(len(days));price=100*np.exp(.0002*x+.03*np.sin(x/12))
    def frame(s,p):
        return pd.DataFrame({'symbol':s,'session':days,'open':p,'close':p,'volume':1e6,'available_at':[calendar.close(d).isoformat() for d in days]})
    bars={s:frame(s,price*(1 if s=='SPY' else 1.1)) for s in ('ABC','SPY','XLK')}
    monkeypatch.setattr(store,'bars',lambda s:bars.get(s,pd.DataFrame()).copy())
    monkeypatch.setattr(store,'warehouse_summary',lambda:[(s,len(days),days[-1]) for s in bars])
    monkeypatch.setattr(SecurityMaster,'resolve',lambda self,s:SimpleNamespace(ticker=s))
    a,_=build_features(store,['ABC'],calendar,'2025-01-01T00:00:00Z',cfg=cfg)
    bars['XLK'].loc[len(days)-1,'close']*=1.2
    b,_=build_features(store,['ABC'],calendar,'2025-01-01T00:00:00Z',cfg=cfg)
    pd.testing.assert_frame_equal(a.iloc[:-1],b.iloc[:-1])
    assert a.iloc[-1].sector_proxy_correlation>.9
    assert a.iloc[-1].sector_proxy_relative!=b.iloc[-1].sector_proxy_relative


def test_earnings_failure_rotates_and_is_optional(store,cfg,monkeypatch):
    from stox.earnings import ingest_earnings
    from stox.security import SecurityMaster
    from stox.providers.alpha import AlphaVantage
    from stox.providers.http import ProviderError
    calls=[]
    monkeypatch.setattr(SecurityMaster,'assets',lambda self:[dict(symbol=s,security_type=t) for s,t in [('AAA','etf'),('ABC','common'),('DEF','common')]])
    monkeypatch.setattr(SecurityMaster,'resolve',lambda self,s:SimpleNamespace(ticker=s))
    def history(self,s):calls.append(s);raise ProviderError('unsupported')
    monkeypatch.setattr(AlphaVantage,'history',history)
    cfg.earnings_symbols_per_run=1
    for _ in range(3):ingest_earnings(cfg,store,['AAA','ABC','DEF'],'2026-10-11T12:00:00Z')
    assert calls==['ABC','DEF']


def test_prospective_horizon_rank_used(store):
    from stox.predictions import performance
    from stox.storage import encode
    store.db.execute('INSERT INTO forecasts VALUES(?,?,?,?,?)',('x','2025-01-01T00:00:00Z','ABC','2025-01-02',encode({'forecasts':[{'horizon':60,'horizon_rank':2,'qualified':False,'p_gain':.6,'expected_return':.03}],'metadata':{'run_mode':'live'}})))
    store.db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?)',('x',60,'2025-03-03',.05,encode({'benchmarks':{}})));store.db.commit()
    v=performance(store)['research_only']['horizons']['60']
    assert v['top3_hit_rate']==1 and v['top20_mean_net']==.05


def test_optional_signals_expire(store,cfg):
    from stox.features import enrich
    cfg.enable_options_signals=True
    r=dict(symbol='ABC',license_confirmed=True,source_url='https://example.org',available_at='2025-01-01T00:00:00Z',observed_at='2025-01-01T00:00:00Z',values={'options_iv30':.3})
    store.record('external_options','x',r,r['available_at'])
    f=pd.DataFrame({'symbol':['ABC','ABC'],'issue_at':['2025-01-02T00:00:00Z','2025-03-01T00:00:00Z']})
    out=enrich(f,store,cfg)
    assert out.iloc[0].options_iv30==.3 and np.isnan(out.iloc[1].options_iv30)


def test_sec_unmapped_assets_do_not_starve_refresh(store):
    from stox.ingestion import sec_refresh_symbols
    mapping={'ABC':'123','DEF':'456'}
    symbols=['AAA','AAB','ABC','DEF']
    assert sec_refresh_symbols(symbols,mapping,store,1)==['ABC']
    store.advance('sec:123','2026-10-11T12:00:00Z')
    assert sec_refresh_symbols(symbols,mapping,store,1)==['DEF']
    assert sec_refresh_symbols(['AAA'],mapping,store,1)==[]
