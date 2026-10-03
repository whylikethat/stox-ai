from __future__ import annotations
import numpy as np
import pandas as pd
from .calendar import MarketCalendar
from .storage import Store
from .holdings import add


def seed(cfg, end='2025-12-19'):
    cfg.initialize()
    store=Store(cfg.root)
    if store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]:
        raise ValueError('Demo must use a separate empty data root')
    cal=MarketCalendar()
    sessions=cal.sessions('2014-01-02',end)
    rng=np.random.default_rng(271828)
    market=rng.normal(.0003,.008,len(sessions))
    stamp=cal.close(sessions[-1])+pd.Timedelta(hours=2)
    assets=[]
    for i,symbol in enumerate(('SPY','QQQ','DEMOA','DEMOB','DEMOC','DEMOD','DEMOE','DEMOF')):
        cyc=np.sin(np.arange(len(sessions))/90+i)*.0006
        returns=market*(.6+.1*i)+rng.normal(.00025,.005,len(sessions))+cyc
        price=(40+i*15)*np.cumprod(1+returns)
        opens=np.r_[price[0],price[:-1]]*(1+rng.normal(0,.001,len(sessions)))
        rows=[]
        for j,s in enumerate(sessions):
            rows.append({'symbol':symbol,'session':s,'open':float(opens[j]),'close':float(price[j]),
                         'high':float(max(opens[j],price[j])*1.005),'low':float(min(opens[j],price[j])*.995),
                         'volume':float(2_000_000+rng.integers(0,1_000_000)),'provider':'synthetic',
                         'available_at':cal.close(s).isoformat(),'ingested_at':stamp.isoformat()})
        store.put_bars(symbol,pd.DataFrame(rows))
        asset={'id':'synthetic-'+symbol,'symbol':symbol,'name':symbol+' Common Stock' if i>1 else symbol+' ETF',
               'tradable':True,'class':'us_equity','exchange':'NASDAQ','status':'active','security_type':'common' if i>1 else 'etf'}
        store.record('assets',asset['id'],asset,cal.open(sessions[0]).isoformat())
        assets.append(asset)
        store.advance('bars:'+symbol,sessions[-1])
    for key in ('actions','news','sec','fred'):
        store.advance(key,stamp.isoformat())
    from .security import SecurityMaster
    SecurityMaster(store).refresh(assets,stamp.isoformat())
    if not store.db.execute('SELECT 1 FROM holdings').fetchone():
        add(store,'DEMOA',sessions[-50],float(store.bars('DEMOA').iloc[-50].close),10)
    store.close()
    return stamp.isoformat()
