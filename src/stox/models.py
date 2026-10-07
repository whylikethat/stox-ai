from __future__ import annotations
import math
from pathlib import Path
import joblib
import os
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
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
    def __init__(self,algorithm,columns,horizon):
        self.algorithm,self.columns,self.horizon = algorithm,list(columns),horizon
        self.binary,self.calibrators={},{}

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
        self.train_through=str(train.label_end.max())
        self.calibration_through=str(calibration.label_end.max())
        self.reference=np.nanmedian(X,axis=0)
        self.reference=np.nan_to_num(self.reference)
        return self

    def predict(self,frame):
        X=frame[self.columns].to_numpy(dtype=float)
        # Enforce coherent nested exceedance probabilities using monotone projection.
        raw=np.column_stack([self.calibrators[t].predict(self.binary[t].predict(X)) for t in THRESHOLDS])
        from sklearn.isotonic import isotonic_regression
        probabilities=np.array([isotonic_regression(r,increasing=False) for r in raw])
        expected=self.reg.predict(X)
        quant=np.sort(np.column_stack([m.predict(X) for m in self.quantiles.values()]),axis=1)
        return probabilities,expected,quant

    def explain(self,row):
        frame=pd.DataFrame([row])
        original=self.predict(frame)[0][0,3]
        output=[]
        for i,c in enumerate(self.columns):
            altered=frame.copy()
            altered[c]=self.reference[i]
            contribution=float(original-self.predict(altered)[0][0,3])
            output.append({'feature':c,'probability_change_from_reference':contribution})
        return sorted(output,key=lambda r:abs(r['probability_change_from_reference']),reverse=True)[:6]


def fit_calibrated(frame, algorithm, columns,horizon):
    days=sorted(frame.session.unique())
    if len(days)<100:
        raise ValueError('Insufficient training dates')
    cut=days[int(len(days)*.75)]
    train,cal=temporal_split(frame,cut)
    if len(train)<100 or len(cal)<40:
        raise ValueError('Insufficient purged training/calibration support')
    return ForecastModel(algorithm,columns,horizon).fit(train,cal)


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
    development,holdout=temporal_split(data,holdout_start)
    d_days=sorted(development.session.unique())
    families=[('price',FAMILIES['price'])]
    for family,columns in FAMILIES.items():
        if family!='price' and development[columns].notna().mean().mean()>=.4:
            families.append(('price+'+family,FAMILIES['price']+columns))
    experiments=[]
    for family,columns in families:
        for algorithm in ('logistic','histogram'):
            fold_metrics=[]
            for fraction in (.60,.80):
                cut=d_days[int(len(d_days)*fraction)]
                train,valid=temporal_split(development,cut)
                if fraction==.60:
                    valid=valid[valid.session<d_days[int(len(d_days)*.80)]]
                if len(valid)<40:
                    continue
                model=fit_calibrated(train,algorithm,columns,horizon)
                p,e,_=model.predict(valid)
                fold_metrics.append(metrics(valid,p[:,3],e,horizon))
            if fold_metrics:
                score=float(np.mean([m['brier']+m['ece'] for m in fold_metrics]))
                experiments.append({'family':family,'algorithm':algorithm,'columns':columns,'score':score,'folds':fold_metrics})
    if not experiments:
        raise ValueError('No valid walk-forward experiments')
    experiments.sort(key=lambda x:(x['score'],len(x['columns'])))
    chosen=experiments[0]
    # Optional family must improve over the best baseline by >= 0.005 on development only.
    baseline=min((e for e in experiments if e['family']=='price'),key=lambda x:x['score'])
    if chosen['family']!='price' and baseline['score']-chosen['score']<.005:
        chosen=baseline
    champion=fit_calibrated(development,chosen['algorithm'],chosen['columns'],horizon)
    p,e,q=champion.predict(holdout)
    evaluation=metrics(holdout,p[:,3],e,horizon)
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
    champion.metadata={'horizon':horizon,'algorithm':chosen['algorithm'],'family':chosen['family'],
                       'holdout_start':holdout_start,'holdout_end':str(holdout.session.max()),
                       'train_through':champion.train_through,'calibration_through':champion.calibration_through,
                       'experiments':experiments,'evaluation':evaluation,'threshold':threshold,
                       'validated':bool(valid and threshold is not None),'created_at':now_iso(),
                       'label_definition':'next-regular-open/calendar-day-target/first-close/net-total-return-v1',
                       'training_rows':len(data),'data_digest':digest(data[['symbol','session','target']].to_dict('records'))}
    # An independently selected alternative is retained for disagreement, never arbitrary averaging.
    alternative=next((x for x in experiments if x['algorithm']!=chosen['algorithm'] and x['family']=='price'),None)
    champion.committee=fit_calibrated(development,alternative['algorithm'],alternative['columns'],horizon) if alternative else None
    if champion.committee:
        other=champion.committee.predict(holdout)[0][:,3]
        champion.metadata['agreement_p90']=float(np.quantile(np.abs(other-p[:,3]),.9))
    return champion,holdout


def registry_train(labels,cfg,store,force=False,stamp=None,progress=None):
    stamp=stamp or now_iso()
    results={}
    with threadpool_limits(limits=cfg.threads):
        for index,horizon in enumerate(cfg.horizons):
            if progress: progress.update(processed=index,horizon=horizon,force=True)
            existing=store.db.execute("SELECT * FROM models WHERE horizon=? AND status='champion' ORDER BY created_at DESC LIMIT 1",(horizon,)).fetchone()
            old=joblib.load(store.root/existing['path']) if existing else None
            new_count=int(((labels.horizon==horizon)&(labels.label_end>(old.metadata['holdout_end'] if old else '1900-01-01'))).sum()) if not labels.empty else 0
            age=(pd.Timestamp(stamp)-pd.Timestamp(existing['created_at'])).days if existing else 10**6
            if old and not force and (age<cfg.retrain_days or new_count<cfg.min_new_labels):
                results[horizon]=old
                continue
            try:
                candidate,holdout=train_horizon(labels,horizon,cfg)
            except ValueError as exc:
                store.health(f'model:{horizon}','WARN',str(exc))
                if old:
                    results[horizon]=old
                continue
            promote=old is None
            if old is not None:
                # Evaluate both only on outcomes that neither fitted estimator/calibrator has seen.
                boundary=max(old.calibration_through,candidate.calibration_through)
                comparison=holdout[pd.to_datetime(holdout.session)>pd.Timestamp(boundary)+pd.Timedelta(days=5)]
                if len(comparison)>=cfg.min_bucket_samples and len(set(independent_blocks(comparison,horizon)))>=cfg.min_validation_blocks:
                    op=old.predict(comparison)[0][:,3]
                    cp=candidate.predict(comparison)[0][:,3]
                    y=(comparison.target.to_numpy()>0).astype(int)
                    differences=(op-y)**2-(cp-y)**2
                    blocks=independent_blocks(comparison,horizon)
                    b=pd.Series(differences).groupby(blocks).mean()
                    improvement=float(b.mean()-1.96*b.std(ddof=1)/np.sqrt(len(b)))
                    promote=improvement>0 and candidate.metadata['evaluation']['ece']<=old.metadata['evaluation']['ece']
                    candidate.metadata['promotion_lower_improvement']=improvement
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
            with store.db:
                if promote:
                    store.db.execute("UPDATE models SET status='retired' WHERE horizon=? AND status='champion'",(horizon,))
                store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',(mid,horizon,stamp,'champion' if promote else 'challenger',str(rel),encode(candidate.metadata)))
                store.db.execute('INSERT INTO evaluations VALUES(?,?,?)',(mid,'backtest',encode(candidate.metadata['evaluation'])))
            results[horizon]=candidate if promote else old
            store.health(f'model:{horizon}','PASS' if results[horizon].metadata['validated'] else 'WARN','Validated champion' if results[horizon].metadata['validated'] else 'Research model; recommendation qualification has not passed')
    if progress: progress.update(processed=len(cfg.horizons))
    return results
