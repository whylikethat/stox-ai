"""Contract for licensed point-in-time adapters. No paid endpoint or scraping enabled."""
from typing import Protocol
import numpy as np
import pandas as pd

class SignalAdapter(Protocol):
    provider: str
    def fetch(self, symbols: list[str], since: str) -> list[dict]:
        """Return symbol, available_at, observed_at, source_url, family and numeric values.

        Adapters must enforce licensing, request budgets, revision provenance and caching.
        No adapter is activated merely because a credential exists.
        """
        ...


def enrich_optional(frame,store,cfg):
    from ..features import FAMILIES,asof_values
    result=frame.copy()
    for family in ('analyst','options'):
        if cfg is None or not getattr(cfg,'enable_'+family+'_signals',False): continue
        rows=store.records('external_'+family)
        for symbol,indices in result.groupby('symbol').groups.items():
            for feature in FAMILIES[family]:
                usable=[]
                for row in rows:
                    if row.get('symbol')!=symbol or not row.get('license_confirmed') or not row.get('source_url'): continue
                    val=row.get('values',{}).get(feature)
                    if isinstance(val,bool) or not isinstance(val,(int,float)) or not np.isfinite(val) or not row.get('available_at') or not row.get('observed_at'): continue
                    # Without audited historical vintages, first local observation is the earliest safe time.
                    stamp=max(pd.Timestamp(row['available_at']),pd.Timestamp(row['observed_at']))
                    if stamp.tzinfo is None: continue
                    usable.append({'available_at':stamp.isoformat(),'end':stamp.isoformat(),'value':val})
                if usable:
                    times=pd.to_datetime(result.loc[indices,'issue_at'],utc=True,format='mixed')
                    values=asof_values(times,usable,'value')
                    stamps=np.sort(np.array([pd.Timestamp(r['available_at']).value for r in usable]))
                    positions=np.searchsorted(stamps,times.astype('int64'),side='right')-1
                    age=(times.astype('int64').to_numpy()-stamps[np.maximum(positions,0)])/86400e9
                    values[(positions<0)|(age>30)]=np.nan
                    result.loc[indices,feature]=values
    return result


def import_signals(store,rows):
    """Bounded, atomic licensed export import. Never backdate local availability."""
    from ..security import SecurityMaster
    from ..storage import now_iso,digest
    from ..features import FAMILIES
    from urllib.parse import urlsplit
    if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Expected at most 10,000 signal records')
    master=SecurityMaster(store);observed=now_iso();clean=[]
    for row in rows:
        family=row.get('family')
        if family not in ('analyst','options') or row.get('license_confirmed') is not True:raise ValueError('Licensed analyst/options data required')
        if urlsplit(row.get('source_url','')).scheme!='https':raise ValueError('HTTPS source URL required')
        symbol=master.resolve(row['symbol']).ticker
        available=pd.Timestamp(row['available_at'])
        if available.tzinfo is None or pd.isna(available):raise ValueError('Timezone-aware publication timestamp required')
        values=row.get('values',{})
        if not values or any(k not in FAMILIES[family] or isinstance(v,bool) or not isinstance(v,(float,int)) or not np.isfinite(v) for k,v in values.items()):raise ValueError('Unsupported or non-finite signal values')
        economic={'symbol':symbol,'family':family,'available_at':available.isoformat(),'source_url':row['source_url'],'license_confirmed':True,'values':values}
        clean.append((family,digest(economic),{**economic,'observed_at':observed}))
    inserted=0
    with store.transaction():
        for family,key,row in clean:
            if store.db.execute('SELECT 1 FROM records WHERE kind=? AND record_id=?',('external_'+family,key)).fetchone():continue
            store.record('external_'+family,key,row,observed);inserted+=1
        for family in {v[0] for v in clean}:store.health(family,'PASS','Licensed local export imported; first observation enforced')
    return inserted
