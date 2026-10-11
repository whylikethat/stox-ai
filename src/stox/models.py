from __future__ import annotations
import math
from pathlib import Path
import joblib
import os
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .features import FAMILIES
from .storage import digest, encode, now_iso

THRESHOLDS = [-.20,-.10,-.05,0.,.02,.05]

def wilson(successes, count, z=1.96):
    if count <= 0:
        return 0.,1.
    p = successes/count
    d = 1+z*z/count
    center = (p+z*z/(2*count))/d
    half = z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/d
    return max(0,center-half),min(1,center+half)

def temporal_split(frame, cutoff, embargo_days=5):
    boundary = pd.Timestamp(cutoff)-pd.Timedelta(days=embargo_days)
    train = frame[pd.to_datetime(frame.label_end) < boundary]
    test = frame[pd.to_datetime(frame.session) >= pd.Timestamp(cutoff)]
    return train,test

def independent_blocks(frame, horizon):
    dates = pd.to_datetime(frame.session)
    if frame.empty:
        return np.array([],dtype=int)
    return ((dates-dates.min()).dt.days//(horizon+5)).to_numpy()

def metrics(frame, probability, expected, horizon):
    y = frame.target.to_numpy()
    wins = (y>0).astype(int)
    bucket = np.clip((probability*10).astype(int),0,9)
    buckets = []
    for b in sorted(set(bucket)):
        mask = bucket==b
        blocks = independent_blocks(frame[mask],horizon)
        block_rates = pd.Series(wins[mask]).groupby(blocks).mean().to_numpy()
        # Block count, not row count, determines uncertainty to reduce overlap/cross-sectional overconfidence.
        lo,hi = wilson(float(block_rates.sum()),len(block_rates))
        buckets.append({'bucket':int(b),'n':int(mask.sum()),'blocks':len(block_rates),
                        'probability':float(probability[mask].mean()),'win_rate':float(wins[mask].mean()),'interval':[lo,hi]})
    ece = sum(b['n']*abs(b['win_rate']-b['probability']) for b in buckets)/max(1,len(y))
    selections = frame[['session','symbol','target']].copy()
    selections['p'],selections['expected'] = probability,expected
    picks = selections.sort_values(['session','p','expected'],ascending=[True,False,False]).groupby('session').head(3)
    first = picks.groupby('session').head(1)
    # Non-overlapping cohorts are the only returns used for compounded strategy summaries.
    chosen_dates=[]
    for day in sorted(picks.session.unique()):
        if not chosen_dates or (pd.Timestamp(day)-pd.Timestamp(chosen_dates[-1])).days >= horizon+5:
            chosen_dates.append(day)
    curve = picks[picks.session.isin(chosen_dates)].groupby('session').target.mean()
    equity = np.cumprod(1+curve.to_numpy())
    drawdown = equity/np.maximum.accumulate(np.r_[1,equity])[1:]-1 if len(equity) else np.array([0])
    result={'n':len(y),'blocks':len(set(independent_blocks(frame,horizon))),
            'brier':float(brier_score_loss(wins,probability)), 'base_brier':float(np.mean((wins-wins.mean())**2)),
            'ece':float(ece),'return_mae':float(mean_absolute_error(y,expected)),
            'win_rate':float(wins.mean()),'top1_hit_rate':float((first.target>0).mean()),
            'top3_hit_rate':float((picks.target>0).mean()),'mean_return':float(y.mean()),
            'median_return':float(np.median(y)),'worst_loss':float(y.min()),
            'top3_nonoverlap_total_return':float(equity[-1]-1) if len(equity) else None,
            'top3_nonoverlap_max_drawdown':float(drawdown.min()),'strategy_cohorts':len(curve),'buckets':buckets}
    result['benchmark_excess']={s:float(np.nanmean(y-frame['benchmark_'+s].to_numpy())) if 'benchmark_'+s in frame and frame['benchmark_'+s].notna().any() else None for s in ('SPY','QQQ')}
    result['expected_vs_realized']={'mean_expected':float(np.mean(expected)),'mean_realized':float(np.mean(y))}
    result['ranking_spearman']=float(pd.Series(expected).corr(pd.Series(y),method='spearman')) if np.std(expected)>0 and np.std(y)>0 else None
    first_curve=first[first.session.isin(chosen_dates)].set_index('session').target
    first_equity=np.cumprod(1+first_curve.to_numpy())
    result['top1_nonoverlap_total_return']=float(first_equity[-1]-1) if len(first_equity) else None
    result['top1_nonoverlap_max_drawdown']=float((first_equity/np.maximum.accumulate(np.r_[1,first_equity])[1:]-1).min()) if len(first_equity) else None
    return result

class BinaryModel:
    def __init__(self, algorithm):
        self.algorithm=algorithm
        self.constant=None

    def fit(self,X,y):
        if len(np.unique(y))<2:
            self.constant=float(np.mean(y))
            return self
        model = LogisticRegression(C=.1,max_iter=400,random_state=17) if self.algorithm=='logistic' else HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=12,l2_regularization=10,early_stopping=False,random_state=17)
        if self.algorithm=='extra_trees':
            model=ExtraTreesClassifier(n_estimators=48,max_depth=10,min_samples_leaf=40,max_features=.8,n_jobs=1,random_state=17)
        self.model = make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),model)
        self.model.fit(X,y)
        return self

    def predict(self,X):
        return np.full(len(X),self.constant) if self.constant is not None else self.model.predict_proba(X)[:,1]

class Sigmoid:
    def fit(self,p,y):
        self.constant = float(np.mean(y)) if len(np.unique(y))<2 else None
        if self.constant is None:
            self.model=LogisticRegression(C=1,max_iter=300,random_state=17).fit(self.logit(p),y)
        return self

    @staticmethod
    def logit(p):
        p=np.clip(p,1e-5,1-1e-5)
        return np.log(p/(1-p)).reshape(-1,1)

    def predict(self,p):
        return np.full(len(p),self.constant) if self.constant is not None else self.model.predict_proba(self.logit(p))[:,1]

class ForecastModel:
    def __init__(self,algorithm,columns,horizon,distribution='independent'):
        self.algorithm,self.columns,self.horizon = algorithm,list(columns),horizon
        self.binary,self.calibrators={},{}
        self.distribution=distribution

    def fit(self, train, calibration):
        X=train[self.columns].to_numpy(dtype=float)
        C=calibration[self.columns].to_numpy(dtype=float)
        y=train.target.to_numpy()
        for t in THRESHOLDS:
            model=BinaryModel(self.algorithm).fit(X,(y>t).astype(int))
            cal=Sigmoid().fit(model.predict(C),(calibration.target.to_numpy()>t).astype(int))
            self.binary[t],self.calibrators[t]=model,cal
        reg = Ridge(alpha=10) if self.algorithm=='logistic' else HistGradientBoostingRegressor(max_iter=80,max_leaf_nodes=12,l2_regularization=10,early_stopping=False,random_state=17)
        self.reg=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),reg).fit(X,y)
        self.quantiles={}
        for q in (.10,.50,.90):
            model=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),HistGradientBoostingRegressor(loss='quantile',quantile=q,max_iter=60,max_leaf_nodes=10,l2_regularization=10,early_stopping=False,random_state=17))
            model.fit(X,y)
            self.quantiles[q]=model
        # Empirical within-bin supports use training outcomes only. Probabilities,
        # means and quantiles of the challenger all derive from this one distribution.
        edges=np.r_[-np.inf,THRESHOLDS,np.inf]
        supports=[]
        self.bin_support_counts=[]
        for lo,hi in zip(edges[:-1],edges[1:]):
            values=y[(y>lo)&(y<=hi)]
            self.bin_support_counts.append(len(values))
            if len(values): support=np.quantile(values,np.linspace(.01,.99,41))
            else:
                fallback=(hi-.10 if not np.isfinite(lo) else lo+.10 if not np.isfinite(hi) else (lo+hi)/2)
                support=np.full(41,fallback)
            supports.extend(support)
        self.distribution_support=np.array(supports)
        self.train_through=str(train.label_end.max())
        self.calibration_through=str(calibration.label_end.max())
        self.date_ranges={'train':[str(train.session.min()),str(train.session.max())],
                          'calibration':[str(calibration.session.min()),str(calibration.session.max())]}
        self.reference=np.nanmedian(X,axis=0)
        self.reference=np.nan_to_num(self.reference)
        return self

    def predict(self,frame):
        X=frame[self.columns].to_numpy(dtype=float)
        # Enforce coherent nested exceedance probabilities using monotone projection.
        raw=np.column_stack([self.calibrators[t].predict(self.binary[t].predict(X)) for t in THRESHOLDS])
        from sklearn.isotonic import isotonic_regression
        probabilities=np.array([isotonic_regression(r,increasing=False) for r in raw])
        if getattr(self,'distribution','independent')=='coherent':
            expected,quant=self.coherent_summary(probabilities)
            return probabilities,expected,quant
        expected=self.reg.predict(X)
        quant=np.sort(np.column_stack([m.predict(X) for m in self.quantiles.values()]),axis=1)
        return probabilities,expected,quant

    def coherent_summary(self,probabilities):
        masses=np.maximum(0,np.diff(np.column_stack([np.ones(len(probabilities)),probabilities,np.zeros(len(probabilities))])*-1,axis=1))
        weights=np.repeat(masses/41,41,axis=1)
        expected=weights@self.distribution_support
        cdf=np.cumsum(weights,axis=1)
        quant=np.column_stack([self.distribution_support[np.minimum((cdf<q).sum(axis=1),len(self.distribution_support)-1)] for q in (.1,.5,.9)])
        return expected,quant

    def explain(self,row):
        # Independent row perturbations can be inferred together. This preserves
        # the attribution definition while avoiding hundreds of one-row calls.
        frame=pd.DataFrame([dict(row) for _ in range(len(self.columns)+1)])
        for i,column in enumerate(self.columns): frame.loc[i+1,column]=self.reference[i]
        probabilities=self.predict(frame)[0][:,3]
        output=[{'feature':column,'probability_change_from_reference':float(probabilities[0]-probabilities[i+1])} for i,column in enumerate(self.columns)]
        return sorted(output,key=lambda r:abs(r['probability_change_from_reference']),reverse=True)[:6]


def fit_calibrated(frame, algorithm, columns,horizon,distribution='independent'):
    days=sorted(frame.session.unique())
    if len(days)<100:
        raise ValueError('Insufficient training dates')
    cut=days[int(len(days)*.75)]
    train,cal=temporal_split(frame,cut)
    if len(train)<100 or len(cal)<40:
        raise ValueError('Insufficient purged training/calibration support')
    return ForecastModel(algorithm,columns,horizon,distribution).fit(train,cal)


def train_horizon(frame,horizon,cfg):
    data=frame[(frame.horizon==horizon)&(frame.history_count>=cfg.min_history)&(frame.missing_recent==0)&(frame.close>=cfg.min_price)&(frame.dollar_volume>=cfg.min_dollar_volume)].copy()
    data=data.sort_values(['session','symbol']).reset_index(drop=True)
    # Deterministic date-stratified cap, never a random temporal split.
    if len(data)>cfg.max_training_rows:
        stride=int(np.ceil(len(data)/cfg.max_training_rows))
        data=data.iloc[::stride].copy()
    days=sorted(data.session.unique())
    if len(days)<500:
        raise ValueError(f'{horizon}D: fewer than 500 mature historical feature dates')
    holdout_start=days[int(len(days)*.80)]
    preholdout,holdout=temporal_split(data,holdout_start)
    promotion_start=days[int(len(days)*.70)]
    development,promotion=temporal_split(preholdout,promotion_start)
    d_days=sorted(development.session.unique())
    families=[('price',FAMILIES['price'])]
    for family,columns in FAMILIES.items():
        available=[c for c in columns if c in development and development[c].notna().mean()>=.4]
        if family!='price' and available:
            families.append(('price+'+family,FAMILIES['price']+available))
    experiments=[]
    for family,columns in families:
        for algorithm in cfg.model_algorithms:
            fold_metrics=[]
            coherent_metrics=[]
            for fraction in (.60,.80):
                cut=d_days[int(len(d_days)*fraction)]
                train,valid=temporal_split(development,cut)
                if fraction==.60:
                    valid=valid[valid.session<d_days[int(len(d_days)*.80)]]
                if len(valid)<40:
                    continue
                model=fit_calibrated(train,algorithm,columns,horizon)
                p,e,q=model.predict(valid)
                m=metrics(valid,p[:,3],e,horizon)
                m['conflict_rate']=float(np.mean(((p[:,3]>.55)&(q[:,1]<0))|((p[:,3]<.45)&(q[:,1]>0))))
                fold_metrics.append(m)
                model.distribution='coherent'
                cp,ce,cq=model.predict(valid)
                cm=metrics(valid,cp[:,3],ce,horizon)
                cm['conflict_rate']=float(np.mean(((cp[:,3]>.55)&(cq[:,1]<0))|((cp[:,3]<.45)&(cq[:,1]>0))))
                coherent_metrics.append(cm)
            if fold_metrics:
                score=float(np.mean([m['brier']+m['ece'] for m in fold_metrics]))
                experiments.append({'family':family,'algorithm':algorithm,'distribution':'independent','columns':columns,'score':score,'folds':fold_metrics})
                # Same calibrated probabilities: select coherent returns only with development
                # conflict improvement and <=5% return-MAE degradation. Never inspect holdout.
                mae=np.mean([m['return_mae'] for m in fold_metrics])
                coherent_ok=np.mean([m['return_mae'] for m in coherent_metrics])<=1.05*mae and np.mean([m['conflict_rate'] for m in coherent_metrics])<np.mean([m['conflict_rate'] for m in fold_metrics])
                experiments.append({'family':family,'algorithm':algorithm,'distribution':'coherent','columns':columns,'score':score,'folds':coherent_metrics,'eligible':bool(coherent_ok)})
    if not experiments:
        raise ValueError('No valid walk-forward experiments')
    experiments.sort(key=lambda x:(x['score'],len(x['columns']),x['distribution']!='coherent'))
    eligible=[e for e in experiments if e.get('eligible',True)]
    chosen=eligible[0]
    # Optional family must improve over the best baseline by >= 0.005 on development only.
    baseline=min((e for e in eligible if e['family']=='price'),key=lambda x:x['score'])
    if chosen['family']!='price' and baseline['score']-chosen['score']<.005:
        chosen=baseline
    champion=fit_calibrated(development,chosen['algorithm'],chosen['columns'],horizon,chosen['distribution'])
    p,e,q=champion.predict(holdout)
    evaluation=metrics(holdout,p[:,3],e,horizon)
    evaluation['conflict_rate']=float(np.mean(((p[:,3]>.55)&(q[:,1]<0))|((p[:,3]<.45)&(q[:,1]>0))))
    evaluation['interval_80_coverage']=float(((holdout.target>=q[:,0])&(holdout.target<=q[:,2])).mean())
    evaluation['tail_brier']={str(t):float(brier_score_loss((holdout.target>t).astype(int),p[:,i])) for i,t in enumerate(THRESHOLDS)}
    # Threshold selection uses development fold reliability, never holdout returns.
    pooled={}
    for fold in chosen['folds']:
        for b in fold['buckets']:
            pooled.setdefault(b['bucket'],[]).append(b)
    buckets=[]
    for number,group in pooled.items():
        count=sum(b['n'] for b in group)
        blocks=max(0,sum(b['blocks'] for b in group)-len(group)+1)
        rate=sum(b['win_rate']*b['n'] for b in group)/count
        probability=sum(b['probability']*b['n'] for b in group)/count
        if count>=cfg.min_bucket_samples and blocks>=cfg.min_validation_blocks and wilson(rate*blocks,blocks)[0]>.5 and abs(probability-rate)<=cfg.max_calibration_error:
            buckets.append({'bucket':number})
    threshold=min((b['bucket']/10 for b in buckets),default=None)
    valid=evaluation['ece']<=cfg.max_calibration_error and evaluation['brier']<=evaluation['base_brier'] and evaluation['blocks']>=cfg.min_validation_blocks
    champion.metadata={'feature_columns':chosen['columns'],'available_feature_families':[name for name,cols in FAMILIES.items() if development[[c for c in cols if c in development]].notna().any().any()],'horizon':horizon,'algorithm':chosen['algorithm'],'family':chosen['family'],
                       'distribution':chosen['distribution'],'distribution_bin_counts':champion.bin_support_counts,'model_design_version':4,'promotion_start':promotion_start,
                       'family_decisions':{name:('selected' if ('price' if name=='price' else 'price+'+name)==chosen['family'] else 'evaluated; not selected' if any(f==('price' if name=='price' else 'price+'+name) for f,c in families) else 'insufficient point-in-time development coverage') for name in FAMILIES},
                       'family_coverage':{name:{c:float(development[c].notna().mean()) if c in development else 0. for c in cols} for name,cols in FAMILIES.items()},
                       'holdout_start':holdout_start,'holdout_end':str(holdout.session.max()),
                       'date_ranges':{**champion.date_ranges,'holdout':[str(holdout.session.min()),str(holdout.session.max())]},
                       'train_through':champion.train_through,'calibration_through':champion.calibration_through,
                       'experiments':experiments,'evaluation':evaluation,'threshold':threshold,
                       'validated':bool(valid and threshold is not None),'created_at':now_iso(),
                       'label_definition':'next-regular-open/calendar-day-target/first-close/net-total-return-v1',
                       'training_rows':len(data),'history_start':cfg.history_start,'data_digest':digest(data[['symbol','session','target']].to_dict('records'))}
    # An independently selected alternative is retained for disagreement, never arbitrary averaging.
    alternative=next((x for x in experiments if x['algorithm']!=chosen['algorithm'] and x['family']=='price'),None)
    champion.committee=fit_calibrated(development,alternative['algorithm'],alternative['columns'],horizon) if alternative else None
    if champion.committee:
        other=champion.committee.predict(holdout)[0][:,3]
        champion.metadata['agreement_p90']=float(np.quantile(np.abs(other-p[:,3]),.9))
    champion.promotion_frame=promotion
    return champion,holdout


def validation_diagnostics(metadata,cfg):
    e=metadata['evaluation']
    reasons=[]
    if e['ece']>cfg.max_calibration_error: reasons.append('holdout calibration error exceeds configured maximum')
    if e['brier']>e['base_brier']: reasons.append('holdout Brier score does not beat the base rate')
    if e['blocks']<cfg.min_validation_blocks: reasons.append('insufficient independent holdout blocks')
    if metadata.get('threshold') is None: reasons.append('no development reliability bucket supports a qualification threshold')
    if not metadata['validated'] and not reasons: reasons.append('legacy model marked unvalidated; retrain for full diagnostics')
    return {'validated':metadata['validated'],'learned_threshold':metadata.get('threshold'),
            'holdout_samples':e['n'],'independent_blocks':e['blocks'],
            'brier':e['brier'],'base_brier':e['base_brier'],'calibration_error':e['ece'],
            'supported_reliability_buckets':[b for b in e['buckets'] if b['n']>=cfg.min_bucket_samples and b['blocks']>=cfg.min_validation_blocks and b['interval'][0]>.5 and abs(b['probability']-b['win_rate'])<=cfg.max_calibration_error],
            'date_ranges':metadata.get('date_ranges',{'train':['unknown (legacy)',metadata.get('train_through')],'calibration':['unknown (legacy)',metadata.get('calibration_through')],'holdout':[metadata.get('holdout_start'),metadata.get('holdout_end')]}),
            'failure_reasons':reasons}


def registry_train(labels,cfg,store,force=False,stamp=None,progress=None):
    stamp=stamp or now_iso()
    results={}
    with threadpool_limits(limits=cfg.threads):
        for index,horizon in enumerate(cfg.horizons):
            if progress: progress.update(processed=index,horizon=horizon,force=True)
            existing=store.db.execute("SELECT * FROM models WHERE horizon=? AND status='champion' ORDER BY created_at DESC LIMIT 1",(horizon,)).fetchone()
            old=joblib.load(store.root/existing['path']) if existing else None
            if old and (cfg.history_start<old.metadata.get('history_start',cfg.history_start) or (force and 'history_start' not in old.metadata)):
                # Rebuild legacy/short-history research models once after expansion.
                old=None
            if old and not labels.empty and any(c not in labels or not labels[c].notna().any() for c in old.columns if c not in FAMILIES['price']):
                # Never reuse an enrichment-dependent champion after its inputs are disabled.
                old=None
            evaluated_at=store.checkpoint('evaluation:'+str(horizon)) or (existing['created_at'] if existing else '1900-01-01T00:00:00Z')
            availability='label_available_at' if 'label_available_at' in labels else 'label_end'
            new_count=int(((labels.horizon==horizon)&(pd.to_datetime(labels[availability],utc=True)>pd.Timestamp(evaluated_at))).sum()) if not labels.empty else 0
            age=(pd.Timestamp(stamp)-pd.Timestamp(existing['created_at'])).days if existing else 10**6
            from .trials import active,register
            trial=active(store,horizon)
            attempt=store.checkpoint('evaluation:'+str(horizon))
            initial_upgrade=old is not None and old.metadata.get('model_design_version',0)<4 and not attempt
            due=not attempt or (pd.Timestamp(stamp)-pd.Timestamp(attempt)).days>=cfg.retrain_days
            if old and (trial or (not force and not initial_upgrade and (not due or (age<cfg.retrain_days and old.metadata.get('model_design_version',0)>=4) or new_count<cfg.min_new_labels))):
                results[horizon]=old
                continue
            try:
                from dataclasses import replace
                evaluation_cfg=replace(cfg,max_training_rows=min(cfg.max_training_rows,cfg.challenger_max_rows)) if old else cfg
                candidate,holdout=train_horizon(labels,horizon,evaluation_cfg)
            except ValueError as exc:
                store.advance('evaluation:'+str(horizon),stamp)
                store.health(f'model:{horizon}','WARN',str(exc))
                if old:
                    results[horizon]=old
                continue
            promote=old is None
            # Existing champions are compared using frozen live paired predictions.
            # Historical backtests never repeatedly decide incumbent replacement.
            del candidate.promotion_frame
            mid=digest(candidate.metadata)[:24]
            candidate.model_id=mid
            rel=Path('models')/(mid+'.joblib')
            (store.root/'models').mkdir(exist_ok=True)
            temporary=(store.root/rel).with_suffix('.tmp')
            joblib.dump(candidate,temporary,compress=3)
            with temporary.open('rb') as file: os.fsync(file.fileno())
            temporary.replace(store.root/rel)
            fd=os.open(store.root/'models',os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
            with store.transaction():
                if promote:
                    store.db.execute("UPDATE models SET status='retired' WHERE horizon=? AND status='champion'",(horizon,))
                store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',(mid,horizon,stamp,'champion' if promote else 'challenger',str(rel),encode(candidate.metadata)))
                store.db.execute('INSERT INTO evaluations VALUES(?,?,?)',(mid,'backtest',encode(candidate.metadata['evaluation'])))
                if old is not None: register(store,mid,old.model_id,horizon,stamp,cfg)
                store.advance('evaluation:'+str(horizon),stamp)
            results[horizon]=candidate if promote else old
            store.health(f'model:{horizon}','PASS' if results[horizon].metadata['validated'] else 'WARN','Validated champion' if results[horizon].metadata['validated'] else 'Research model; recommendation qualification has not passed')
    if progress: progress.update(processed=len(cfg.horizons))
    return results



def needs_training_labels(cfg,store,features,stamp,force=False):
    """Inference within the cadence needs no historical label rebuild.

    Missing models, expanded history or unavailable selected inputs force the
    established evaluation/fallback path. After the cadence, exact matured-label
    counts are still computed by registry_train before any training starts.
    """
    import json
    if force: return True
    for horizon in cfg.horizons:
        row=store.db.execute("SELECT created_at,metadata FROM models WHERE horizon=? AND status='champion' ORDER BY created_at DESC LIMIT 1",(horizon,)).fetchone()
        if row is None: return True
        meta=json.loads(row['metadata'])
        if cfg.history_start<meta.get('history_start',cfg.history_start): return True
        for column in meta.get('feature_columns',[]):
            if column not in features or not features[column].notna().any(): return True
        from .trials import active
        if active(store,horizon): continue
        attempt=store.checkpoint('evaluation:'+str(horizon))
        if attempt and (pd.Timestamp(stamp)-pd.Timestamp(attempt)).days<cfg.retrain_days: continue
        if meta.get('model_design_version',0)<4 and not attempt: return True
        if (pd.Timestamp(stamp)-pd.Timestamp(row['created_at'])).days>=cfg.retrain_days: return True
    return False
