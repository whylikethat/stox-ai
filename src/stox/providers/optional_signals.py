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
                    if val is None or not np.isfinite(val) or not row.get('available_at') or not row.get('observed_at'): continue
                    # Without audited historical vintages, first local observation is the earliest safe time.
                    stamp=max(pd.Timestamp(row['available_at']),pd.Timestamp(row['observed_at']))
                    if stamp.tzinfo is None: continue
                    usable.append({'available_at':stamp.isoformat(),'end':stamp.isoformat(),'value':val})
                if usable:
                    result.loc[indices,feature]=asof_values(result.loc[indices,'issue_at'],usable,'value')
    return result
