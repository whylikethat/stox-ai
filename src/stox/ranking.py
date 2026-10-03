from __future__ import annotations
import numpy as np
from threadpoolctl import threadpool_limits
from .universe import eligible

SOFT_TARGETS={20:.015,30:.02,60:.04,90:.06}

def forecast_rows(features, assets, models, cfg, expected_session):
    latest=features.sort_values('session').groupby('symbol').tail(1)
    lookup={a['symbol']:a for a in assets}
    output=[]
    with threadpool_limits(limits=cfg.threads):
        for h,model in models.items():
            p,expected,q=model.predict(latest)
            committee=model.committee.predict(latest)[0][:,3] if model.committee else p[:,3]
            evaluation=model.metadata['evaluation']
            for i,row in enumerate(latest.to_dict('records')):
                reasons=eligible(lookup.get(row['symbol'],{}),row,cfg)
                if row['session']!=expected_session:
                    reasons.append('stale price history')
                if not model.metadata['validated']:
                    reasons.append('model has not passed recommendation validation')
                bucket=next((b for b in evaluation['buckets'] if b['bucket']==min(9,int(p[i,3]*10))),None)
                if not bucket or bucket['n']<cfg.min_bucket_samples or bucket['blocks']<cfg.min_validation_blocks:
                    reasons.append('insufficient comparable calibration support')
                elif bucket['interval'][0]<=.5 or abs(bucket['probability']-bucket['win_rate'])>cfg.max_calibration_error:
                    reasons.append('comparable bucket has insufficient win/calibration evidence')
                threshold=model.metadata['threshold']
                if threshold is None or p[i,3] < threshold:
                    reasons.append('below validated qualification threshold')
                for family,provider in (('news','news'),('fundamentals','sec'),('macro','fred')):
                    if family in model.metadata['family']:
                        # Never substitute imputed defaults for an unavailable selected feature family silently.
                        columns=__import__('stox.features',fromlist=['FAMILIES']).FAMILIES[family]
                        if not any(np.isfinite(row.get(c,np.nan)) for c in columns):
                            reasons.append('selected '+family+' feature family is unavailable')
                if expected[i]<=0:
                    reasons.append('non-positive expected net return')
                if 1-p[i,0]>cfg.max_tail_probability:
                    reasons.append('catastrophic tail estimate exceeds risk policy')
                disagreement=abs(p[i,3]-committee[i])
                rule=max(.01,model.metadata.get('agreement_p90',.05))
                agreement='high' if disagreement<=rule/2 else 'moderate' if disagreement<=rule else 'low'
                result={'symbol':row['symbol'],'name':lookup.get(row['symbol'],{}).get('name',row['symbol']),
                        'horizon':int(h),'p_gain':float(p[i,3]),'p_above_2':float(p[i,4]),'p_above_5':float(p[i,5]),
                        'expected_return':float(expected[i]),'median_return':float(q[i,1]),
                        'p_loss_5':float(1-p[i,2]),'p_loss_10':float(1-p[i,1]),'p_loss_20':float(1-p[i,0]),
                        'quantiles_10_50_90':[float(v) for v in q[i]],
                        'interval_validation_coverage':evaluation['interval_80_coverage'],
                        'distribution_status':'empirical holdout coverage; not a guaranteed interval',
                        'model_agreement':agreement,'model_probabilities':{model.algorithm:float(p[i,3]),'alternative':float(committee[i])},
                        'calibration_support':bucket,'qualified':not reasons,'exclusions':reasons,
                        'probability_resolution':max(.01,(bucket['interval'][1]-bucket['interval'][0])/2) if bucket else 1.,
                        'quality_label':'Meets preferred return' if expected[i]>=SOFT_TARGETS.get(h,0) else 'High Confidence / Lower Return',
                        'close':float(row['close']),'dollar_volume':float(row['dollar_volume']) if np.isfinite(row['dollar_volume']) else None,
                        'volatility':float(row['volatility']) if np.isfinite(row['volatility']) else None,'drawdown':float(row['drawdown']) if np.isfinite(row['drawdown']) else None,
                        'session':row['session'],'model_id':model.model_id,'feature_version':'causal-v2',
                        'feature_families':model.metadata['family'],'model_validated':model.metadata['validated'],
                        'event_warning':'Upcoming earnings status unknown unless a verified calendar event is included',
                        'explanations':[]}
                output.append(result)
    return output

def rank(rows):
    ordered=sorted(rows,key=lambda r:(-r['p_gain'],r['symbol'],r['horizon']))
    groups=[]
    while ordered:
        anchor=ordered[0]
        tolerance=anchor['probability_resolution']
        group=[r for r in ordered if anchor['p_gain']-r['p_gain']<=min(tolerance,r['probability_resolution'])]
        keys={(r['symbol'],r['horizon']) for r in group}
        ordered=[r for r in ordered if (r['symbol'],r['horizon']) not in keys]
        group.sort(key=lambda r:(-r['expected_return'],r['p_loss_20'],r['symbol'],r['horizon']))
        groups.extend(group)
    return [{**r,'rank':i+1} for i,r in enumerate(groups)]

def leaderboards(rows):
    valid=[r for r in rows if r['qualified']]
    return rank([r for r in valid if r['horizon']==30])[:20],rank(valid)[:20]
