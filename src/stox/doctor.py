from __future__ import annotations
import importlib.metadata
import pandas as pd
from .calendar import MarketCalendar,utc
from .storage import Store
from .providers.alpaca import Alpaca
from .providers.sec import SEC
from .providers.fred import FRED
from .providers.alpha import AlphaVantage


def doctor(cfg,live=False):
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
        session,end=cal.sip_end(utc())
        start=cal.open(session).isoformat()
        check('Alpaca credentials/assets',lambda:len(Alpaca(cfg.secrets).assets()))
        def bars():
            rows=list(Alpaca(cfg.secrets).bars(['SPY'],start,end))
            if not any(p.get('SPY') for p in rows):
                raise RuntimeError('No SPY daily bar returned')
            return f'SPY historical SIP bar through {session}'
        check('Alpaca historical SIP',bars)
        check('Alpaca news',lambda:len(next(Alpaca(cfg.secrets).news((utc()-pd.Timedelta(days=3)).isoformat(),utc().isoformat()))),False)
        check('Alpaca corporate actions',lambda:len(next(Alpaca(cfg.secrets).actions((utc()-pd.Timedelta(days=7)).isoformat(),utc().isoformat()))))
        check('SEC',lambda:len(SEC(cfg.secrets.get('SEC_USER_AGENT')).mappings()),False)
        check('FRED/ALFRED',lambda:len(next(FRED(cfg.secrets.get('FRED_API_KEY')).observations('DGS10',(utc()-pd.Timedelta(days=7)).date().isoformat(),utc().isoformat()))),False)
        if cfg.secrets.get('ALPHAVANTAGE_API_KEY'):
            check('Alpha Vantage',lambda:len(AlphaVantage(cfg.secrets['ALPHAVANTAGE_API_KEY'],store,cfg.av_daily_budget).earnings()),False)
    else:
        checks.append({'check':'providers','status':'WARN','detail':'Not contacted. Use stox doctor --live explicitly.'})
    store.close()
    return checks
