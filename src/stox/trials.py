"""Frozen, paired forward tests. No reconstructed historical predictions or repeated peeking."""
import json
import numpy as np
import pandas as pd
import joblib
from threadpoolctl import threadpool_limits
from .storage import encode,now_iso
from .actions import relevant,total_return,UnresolvedAction


def register(store,candidate,incumbent,horizon,stamp,cfg):
    policy={'samples':cfg.min_bucket_samples,'blocks':cfg.min_validation_blocks,'calibration':cfg.max_calibration_error,
            'coverage':cfg.min_core_coverage,'horizon_tests':len(cfg.horizons),'alpha':.05,'friction_bps':cfg.friction_bps,'design':'paired-forward-fixed-once-v1'}
    with store.transaction():
        store.db.execute('INSERT OR IGNORE INTO model_trials VALUES(?,?,?,?,?,?,?)',(candidate,incumbent,horizon,stamp,'collecting',encode(policy),encode({'reason':'Waiting for new paired forecasts and mature independent blocks'})))


def active(store,horizon):
    return store.db.execute("SELECT * FROM model_trials WHERE horizon=? AND status='collecting' ORDER BY started_at LIMIT 1",(horizon,)).fetchone()


def issue_trials(store,current,models,cfg,cal,stamp):
    entry=cal.next_open(stamp)
    with threadpool_limits(limits=cfg.threads):
        for h,champion in models.items():
            trial=active(store,h)
            if not trial:continue
            if trial['incumbent']!=champion.model_id:
                with store.transaction():store.db.execute("UPDATE model_trials SET status='superseded' WHERE candidate=?",(trial['candidate'],))
                continue
            row=store.db.execute('SELECT path FROM models WHERE id=?',(trial['candidate'],)).fetchone()
            try:
                model=joblib.load(store.root/row['path'])
                needed=set(model.columns)|set(champion.columns)
                if any(c not in current or not current[c].notna().any() for c in needed):
                    store.health('trial:'+str(h),'WARN','Selected trial features unavailable; no paired forecasts issued')
                    continue
                f=current[(current.history_count>=cfg.min_history)&(current.missing_recent==0)&(current.close>=cfg.min_price)&(current.dollar_volume>=cfg.min_dollar_volume)].copy()
                existing={r[0] for r in store.db.execute('SELECT symbol FROM trial_forecasts WHERE candidate=? AND entry_session=?',(trial['candidate'],entry))}
                f=f[~f.symbol.isin(existing)]
                if f.empty:continue
                cp,ce,_=model.predict(f);op,oe,_=champion.predict(f)
                policy=json.loads(trial['policy']);target=cal.settle(entry,h)
                with store.transaction():
                    store.db.executemany('INSERT OR IGNORE INTO trial_forecasts VALUES(?,?,?,?,?,?,?,?,?,?)',[(trial['candidate'],s,entry,target,stamp,float(cp[i,3]),float(ce[i]),float(op[i,3]),float(oe[i]),policy['friction_bps']) for i,s in enumerate(f.symbol) if np.isfinite([cp[i,3],ce[i],op[i,3],oe[i]]).all() and 0<=cp[i,3]<=1 and 0<=op[i,3]<=1])
            except (OSError,ValueError,KeyError) as exc:
                store.health('trial:'+str(h),'WARN',str(exc))


def settle_trials(store,cal,stamp):
    completed=cal.completed(stamp);actions=store.records('actions');symbol=None;bars=None
    pending=store.db.execute('''SELECT f.* FROM trial_forecasts f LEFT JOIN trial_outcomes o USING(candidate,symbol,entry_session)
      WHERE o.candidate IS NULL AND f.entry_session<=? ORDER BY f.symbol''',(completed,)).fetchall()
    with store.transaction():
        for r in pending:
            if symbol!=r['symbol']:
                symbol=r['symbol'];bars=store.bars(symbol)
                if not bars.empty:bars=bars.set_index('session')
            if bars.empty or r['entry_session'] not in bars.index:continue
            store.db.execute('INSERT OR IGNORE INTO trial_entries VALUES(?,?,?,?,?)',(r['candidate'],symbol,r['entry_session'],float(bars.loc[r['entry_session'],'open']),stamp))
            if r['target_session']>completed or r['target_session'] not in bars.index:continue
            entry_price=store.db.execute('SELECT price FROM trial_entries WHERE candidate=? AND symbol=? AND entry_session=?',(r['candidate'],symbol,r['entry_session'])).fetchone()[0]
            try:
                y=total_return(entry_price,float(bars.loc[r['target_session'],'close']),r['entry_session'],r['target_session'],relevant(actions,symbol),r['friction'])
            except UnresolvedAction:continue
            store.db.execute('INSERT OR IGNORE INTO trial_outcomes VALUES(?,?,?,?,?)',(r['candidate'],symbol,r['entry_session'],y,stamp))


def assess(store,cfg,stamp):
    from .models import metrics,independent_blocks
    for trial in store.db.execute("SELECT * FROM model_trials WHERE status='collecting'").fetchall():
        policy=json.loads(trial['policy']);h=trial['horizon']
        f=pd.read_sql_query('''SELECT f.*,o.target FROM trial_forecasts f JOIN trial_outcomes o USING(candidate,symbol,entry_session) WHERE candidate=?''',store.db,params=(trial['candidate'],))
        diagnostic={'samples':len(f),'blocks':0,'required_samples':policy['samples'],'required_blocks':policy['blocks'],'reason':'Waiting for mature paired outcomes'}
        status='collecting'
        if not f.empty:
            f['session']=f.entry_session;blocks=independent_blocks(f,h);diagnostic['blocks']=len(set(blocks))
            # Only test once after the final required block has fully matured, avoiding
            # weekly re-testing until a lucky result passes. Extra rows after cutoff ignored.
            first=pd.Timestamp(store.db.execute('SELECT min(entry_session) FROM trial_forecasts WHERE candidate=?',(trial['candidate'],)).fetchone()[0]);last_issue=first+pd.Timedelta(days=policy['blocks']*(h+5)-1)
            end=last_issue+pd.Timedelta(days=h+10)
            ready=pd.Timestamp(stamp).tz_localize(None)>=end
            f=f[pd.to_datetime(f.entry_session)<=last_issue].copy()
            diagnostic['samples']=len(f);diagnostic['blocks']=len(set(independent_blocks(f,h)))
            issued=store.db.execute('SELECT count(*) FROM trial_forecasts WHERE candidate=? AND entry_session<=?',(trial['candidate'],last_issue.date().isoformat())).fetchone()[0]
            diagnostic['settled_coverage']=len(f)/max(1,issued)
            if ready and diagnostic['blocks']>=policy['blocks'] and len(f)>=policy['samples'] and diagnostic['settled_coverage']>=policy.get('coverage',.9):
                blocks=independent_blocks(f,h)
                cm=metrics(f,f.p.to_numpy(),f.expected.to_numpy(),h);om=metrics(f,f.incumbent_p.to_numpy(),f.incumbent_expected.to_numpy(),h)
                y=(f.target>0).astype(int)
                d=((f.incumbent_p-y)**2-(f.p-y)**2).groupby(blocks).mean()
                from scipy.stats import t
                # Bonferroni over the configured horizon tests within this cohort.
                bound=float(d.mean()-t.ppf(1-policy['alpha']/policy.get('horizon_tests',len(cfg.horizons)),len(d)-1)*d.std(ddof=1)/np.sqrt(len(d)))
                passed=bound>0 and cm['ece']<=min(om['ece'],policy['calibration']) and cm['return_mae']<=1.05*om['return_mae']
                diagnostic.update(candidate=cm,incumbent=om,lower_brier_improvement=bound,reason='Paired forward evaluation passed' if passed else 'Paired forward evaluation failed; retain incumbent')
                status='passed' if passed else 'rejected'
                if passed:
                    with store.transaction():
                        current=store.db.execute("SELECT id FROM models WHERE horizon=? AND status='champion'",(h,)).fetchone()
                        if current and current[0]==trial['incumbent']:
                            store.db.execute("UPDATE models SET status='retired' WHERE id=?",(trial['incumbent'],))
                            store.db.execute("UPDATE models SET status='champion' WHERE id=?",(trial['candidate'],))
                        else:status='superseded'
            elif ready:
                status='insufficient'
                diagnostic['reason']='Fixed collection window ended without required evidence; no promotion test performed'
        else:
            first=store.db.execute('SELECT min(entry_session) FROM trial_forecasts WHERE candidate=?',(trial['candidate'],)).fetchone()[0]
            if first and pd.Timestamp(stamp).tz_localize(None)>=pd.Timestamp(first)+pd.Timedelta(days=policy['blocks']*(h+5)-1+h+10):
                status='insufficient'
                diagnostic.update(settled_coverage=0.0,reason='Fixed collection window ended without any settled outcomes; no promotion test performed')
        with store.transaction():store.db.execute('UPDATE model_trials SET status=?,diagnostics=? WHERE candidate=?',(status,encode(diagnostic),trial['candidate']))


def summary(store):
    rows=store.db.execute('SELECT * FROM model_trials ORDER BY started_at DESC').fetchall()
    result=[];seen=set()
    for row in rows:
        if row['horizon'] in seen:continue
        seen.add(row['horizon']);result.append({**dict(row),'policy':json.loads(row['policy']),'diagnostics':json.loads(row['diagnostics'])})
    return result
