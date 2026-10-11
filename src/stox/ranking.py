from __future__ import annotations
import numpy as np
from threadpoolctl import threadpool_limits
from .universe import eligible

SOFT_TARGETS={20:.015,30:.02,60:.04,90:.06}

def consistency(p_gain, expected, quantiles):
    """Flag cross-model contradictions without changing calibrated estimates."""
    q10,median,q90=quantiles
    reasons=[]
    if (p_gain>.55 and median<0) or (p_gain<.45 and median>0):
        reasons.append('gain probability and median imply opposing directions')
    if (p_gain>.60 and q90<=0) or (p_gain<.40 and q10>=0):
        reasons.append('gain probability conflicts with return interval')
    if p_gain>.60 and expected<=0:
        reasons.append('high gain probability but non-positive expected net return')
    return ('conflicting' if reasons else 'no detected conflict'),reasons

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
                if model.metadata.get('distribution')=='coherent':
                    mass=-np.diff(np.r_[1.,p[i],0.])
                    counts=model.metadata.get('distribution_bin_counts',[])
                    if len(counts)!=len(mass) or any(c==0 and m>1e-12 for c,m in zip(counts,mass)):
                        reasons.append('coherent distribution has unsupported return bins')
                disagreement=abs(p[i,3]-committee[i])
                rule=max(.01,model.metadata.get('agreement_p90',.05))
                agreement=('high' if disagreement<=rule/2 else 'moderate' if disagreement<=rule else 'low') if model.committee else 'unavailable'
                consistency_status,consistency_reasons=consistency(float(p[i,3]),float(expected[i]),q[i])
                reasons.extend('forecast inconsistency: '+r for r in consistency_reasons)
                if agreement=='low':
                    reasons.append('low model agreement')
                result={'symbol':row['symbol'],'name':lookup.get(row['symbol'],{}).get('name',row['symbol']),
                        'horizon':int(h),'p_gain':float(p[i,3]),'p_above_2':float(p[i,4]),'p_above_5':float(p[i,5]),
                        'expected_return':float(expected[i]),'median_return':float(q[i,1]),
                        'p_loss_5':float(1-p[i,2]),'p_loss_10':float(1-p[i,1]),'p_loss_20':float(1-p[i,0]),
                        'quantiles_10_50_90':[float(v) for v in q[i]],
                        'interval_validation_coverage':evaluation['interval_80_coverage'],
                        'distribution_status':model.metadata.get('distribution','independent')+'; empirical holdout coverage; not a guaranteed interval',
                        'model_agreement':agreement,'model_probabilities':{model.algorithm:float(p[i,3]),'alternative':float(committee[i]) if model.committee else None},
                        'consistency_status':consistency_status,'consistency_reasons':consistency_reasons,
                        'calibration_support':bucket,'qualified':not reasons,'exclusions':reasons,
                        'probability_resolution':max(.01,(bucket['interval'][1]-bucket['interval'][0])/2) if bucket else 1.,
                        'quality_label':'Validated opportunity' if not reasons else 'Research only',
                        'close':float(row['close']),'dollar_volume':float(row['dollar_volume']) if np.isfinite(row['dollar_volume']) else None,
                        'volatility':float(row['volatility']) if np.isfinite(row['volatility']) else None,'drawdown':float(row['drawdown']) if np.isfinite(row['drawdown']) else None,
                        'session':row['session'],'model_id':model.model_id,'feature_version':row.get('feature_version','causal-v2'),
                        'feature_families':model.metadata['family'],'model_validated':model.metadata['validated'],
                        'event_warning':'Upcoming earnings status unknown unless a verified calendar event is included',
                        'explanations':[]}
                output.append(result)
    return output

def rank(rows):
    """Deterministic probability-first ranking; no expected-return tolerance bands."""
    agreement={'high':0,'moderate':1,'low':2}
    def key(r):
        support=r.get('calibration_support') or {}
        return (not r.get('qualified',False), r.get('consistency_status')=='conflicting',
                -r['p_gain'],r.get('p_loss_10',r.get('p_loss_20',1)),r.get('p_loss_20',1),
                agreement.get(r.get('model_agreement'),3),-support.get('blocks',0),
                -r['expected_return'],-r.get('median_return',0),
                -(r.get('dollar_volume') or 0),r['symbol'],r['horizon'])
    return [{**r,'rank':i+1} for i,r in enumerate(sorted(rows,key=key))]

def leaderboards(rows):
    return rank([r for r in rows if r['horizon']==30])[:20],rank(rows)[:20]

