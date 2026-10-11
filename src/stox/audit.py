"""Read-only run audit. Flags coverage limitations without rewriting historical data."""
import numpy as np
from .features import FAMILIES


def data_audit(features,rows,cfg):
    latest=features.sort_values('session').groupby('symbol').tail(1)
    return {'history_start':str(features.session.min()),'history_end':str(features.session.max()),
            'feature_rows':len(features),'securities':int(features.symbol.nunique()),
            'missing_recent':int((latest.missing_recent!=0).sum()),
            'insufficient_history':int((latest.history_count<cfg.min_history).sum()),
            'revision_unsafe_rows':int((~features.revision_safe.astype(bool)).sum()) if 'revision_safe' in features else 0,
            'feature_coverage':{family:round(float(features[[c for c in columns if c in features]].notna().mean().mean()),4) if any(c in features for c in columns) else 0 for family,columns in FAMILIES.items()},
            'conflicting_forecasts':sum(r.get('consistency_status')=='conflicting' for r in rows),
            'friction_bps':cfg.friction_bps,
            'return_definition':'Next regular-session open to first session close at calendar-day horizon; corporate actions and round-trip friction applied',
            'limits':['Current-universe survivorship bias remains','Sector ETF affinity is a trailing-price proxy, not historical membership','Vendor earnings revisions usable only after first observation']}
