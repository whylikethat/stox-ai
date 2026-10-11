import json
import numpy as np
import pandas as pd
from stox.earnings import parse_earnings,enrich_earnings
from stox.trials import register,active,assess,summary,settle_trials
from stox.storage import SCHEMA


def test_earnings_first_observation_and_revision(store,cfg):
    raw=[{'fiscalDateEnding':'2024-12-31','reportedDate':'2025-02-01','reportedEPS':'2','estimatedEPS':'1','surprisePercentage':'100'}]
    r=parse_earnings('ABC',raw,'2025-03-01T00:00:00Z')[0]
    assert r['available_at'].startswith('2025-03-01')
    store.record('earnings_history','a',r,r['available_at'])
    f=pd.DataFrame({'symbol':['ABC','ABC'],'issue_at':['2025-02-15T00:00:00Z','2025-03-05T00:00:00Z'],'earnings_surprise':[np.nan,np.nan]})
    out=enrich_earnings(f,store,cfg)
    assert np.isnan(out.iloc[0].earnings_surprise) and out.iloc[1].earnings_surprise==1
    assert parse_earnings('ABC',[dict(raw[0],surprisePercentage='NaN')],'2025-03-01T00:00:00Z')==[]
    assert parse_earnings('ABC',[dict(raw[0],reportedDate='NaT')],'2025-03-01T00:00:00Z')==[]


def test_migration_preserves_metadata(store):
    store.advance('sentinel','old')
    store.db.execute('PRAGMA user_version=4');store.db.commit();store.migrate()
    assert store.checkpoint('sentinel')=='old'
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA
    assert store.db.execute("SELECT name FROM sqlite_master WHERE name='trial_entries'").fetchone()


def seed_trial(store,cfg,good=True):
    cfg.min_validation_blocks=8;cfg.min_bucket_samples=100
    for mid,status in [('old','champion'),('new','challenger')]:
        store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',(mid,20,'2024-01-01T00:00:00Z',status,mid+'.joblib','{}'))
    store.db.commit()
    register(store,'new','old',20,'2024-01-01T00:00:00Z',cfg)
    for block in range(8):
        entry=(pd.Timestamp('2024-01-02')+pd.Timedelta(days=25*block)).date().isoformat()
        for n in range(20):
            symbol='S'+str(n);y=.04 if n%2 else -.03;p=.99 if y>0 else .01
            if not good:p=1-p
            store.db.execute('INSERT INTO trial_forecasts VALUES(?,?,?,?,?,?,?,?,?,?)',('new',symbol,entry,entry,'2024-01-01T00:00:00Z',p,y,.6,0,20))
            store.db.execute('INSERT INTO trial_outcomes VALUES(?,?,?,?,?)',('new',symbol,entry,y,'2025-01-01T00:00:00Z'))
    store.db.commit()


def test_forward_trial_fixed_once_preserves_qualification(store,cfg):
    seed_trial(store,cfg)
    # Better predictions still cannot pass before the precommitted window ends.
    assess(store,cfg,'2024-04-01T00:00:00Z');assert active(store,20)
    assess(store,cfg,'2025-01-01T00:00:00Z')
    assert summary(store)[0]['status']=='passed'
    assert store.db.execute("SELECT id FROM models WHERE status='champion'").fetchone()[0]=='new'
    assert store.db.execute("SELECT metadata FROM models WHERE id='new'").fetchone()[0]=='{}'
    before=summary(store);assess(store,cfg,'2025-02-01T00:00:00Z');assert summary(store)==before


def test_failed_trial_never_promotes(store,cfg):
    seed_trial(store,cfg,False);assess(store,cfg,'2025-01-01T00:00:00Z')
    assert summary(store)[0]['status']=='rejected'
    assert store.db.execute("SELECT id FROM models WHERE status='champion'").fetchone()[0]=='old'


def test_trial_issuance_deduplicated_and_missing_family(store,cfg,calendar,monkeypatch):
    from stox.trials import issue_trials
    from types import SimpleNamespace
    class Model:
        columns=['x'];model_id='old'
        def predict(self,f):return np.full((len(f),6),.6),np.zeros(len(f)),np.zeros((len(f),3))
    store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',('new',30,'2025-01-01','challenger','x','{}'));store.db.commit()
    register(store,'new','old',30,'2025-01-01T00:00:00Z',cfg)
    monkeypatch.setattr('stox.trials.joblib.load',lambda p:Model())
    f=pd.DataFrame([dict(symbol='ABC',x=1,history_count=300,missing_recent=0,close=50,dollar_volume=1e8)])
    for _ in range(2):issue_trials(store,f,{30:Model()},cfg,calendar,'2025-01-03T22:00:00Z')
    assert store.db.execute('SELECT count(*) FROM trial_forecasts').fetchone()[0]==1
    assert store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==0


def test_trial_entry_price_frozen_and_settlement_once(store,cfg,calendar,monkeypatch):
    store.db.execute('INSERT INTO trial_forecasts VALUES(?,?,?,?,?,?,?,?,?,?)',('c','ABC','2025-01-06','2025-02-05','2025-01-03T22:00:00Z',.6,.03,.5,.01,20));store.db.commit()
    bars=pd.DataFrame([dict(session='2025-01-06',open=100,close=101),dict(session='2025-02-05',open=108,close=110)])
    monkeypatch.setattr(store,'bars',lambda s:bars)
    settle_trials(store,calendar,'2025-01-07T22:00:00Z')
    assert store.db.execute('SELECT price FROM trial_entries').fetchone()[0]==100
    bars.loc[0,'open']=50
    for _ in range(2):settle_trials(store,calendar,'2025-02-06T22:00:00Z')
    outcomes=store.db.execute('SELECT target FROM trial_outcomes').fetchall()
    assert len(outcomes)==1 and .09<outcomes[0][0]<.11


def test_accession_matched_fundamental_no_future_values():
    from stox.fundamentals import enrich_fundamentals
    rows=[dict(symbol='ABC',namespace='us-gaap',unit='USD',accn='a',end='2024-12-31',available_at='2025-02-01T00:00:00Z',concept='Assets',val=100),dict(symbol='ABC',namespace='us-gaap',unit='USD',accn='a',end='2024-12-31',available_at='2025-02-01T00:00:00Z',concept='CashAndCashEquivalentsAtCarryingValue',val=30)]
    f=pd.DataFrame({'symbol':['ABC','ABC'],'issue_at':['2025-01-01T00:00:00Z','2025-03-01T00:00:00Z']})
    o=enrich_fundamentals(f,rows);assert np.isnan(o.iloc[0].cash_assets) and o.iloc[1].cash_assets==.3


def test_import_signals_license_timestamp_namespace_and_idempotency(store,monkeypatch):
    from stox.providers.optional_signals import import_signals
    from stox.security import SecurityMaster
    from types import SimpleNamespace
    def resolve(self,s):
        if s!='ABC':raise ValueError('Not a ticker')
        return SimpleNamespace(ticker=s)
    monkeypatch.setattr(SecurityMaster,'resolve',resolve)
    row=dict(symbol='ABC',family='options',license_confirmed=True,source_url='https://example.org/export',available_at='2025-01-01T00:00:00Z',values={'options_iv30':.3})
    assert import_signals(store,[row])==1 and import_signals(store,[row])==0
    import pytest
    with pytest.raises(ValueError):import_signals(store,[dict(row,symbol='037833100')])
    with pytest.raises(ValueError):import_signals(store,[dict(row,license_confirmed=False)])


def test_initial_upgrade_evaluation_once_then_checkpoint(cfg,store,monkeypatch):
    import stox.models as m
    from types import SimpleNamespace
    cfg.horizons=(30,)
    stamp='2026-10-11T00:00:00Z'
    store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',('old',30,stamp,'champion','old.joblib','{}'));store.db.commit()
    old=SimpleNamespace(columns=['momentum_20'],model_id='old',metadata={'holdout_end':'2026-10-01','history_start':cfg.history_start})
    monkeypatch.setattr(m.joblib,'load',lambda p:old)
    calls=[]
    def train(*args):calls.append(1);raise ValueError('fixture: insufficient dates')
    monkeypatch.setattr(m,'train_horizon',train)
    labels=pd.DataFrame({'horizon':[30],'label_end':['2026-10-02'],'momentum_20':[.1]})
    assert m.registry_train(labels,cfg,store,stamp=stamp)[30] is old
    assert m.registry_train(labels,cfg,store,stamp=stamp)[30] is old
    assert calls==[1]


def test_collecting_trial_blocks_repeated_forced_training(cfg,store,monkeypatch):
    import stox.models as m
    from types import SimpleNamespace
    cfg.horizons=(30,);stamp='2026-10-11T00:00:00Z'
    store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',('old',30,stamp,'champion','old.joblib','{}'));store.db.commit()
    old=SimpleNamespace(columns=['momentum_20'],model_id='old',metadata={'holdout_end':'2026-10-01','history_start':cfg.history_start})
    register(store,'new','old',30,stamp,cfg)
    monkeypatch.setattr(m.joblib,'load',lambda p:old)
    def fail(*args):raise AssertionError('Frozen trial should not retrain')
    monkeypatch.setattr(m,'train_horizon',fail)
    assert m.registry_train(pd.DataFrame(),cfg,store,force=True,stamp=stamp)[30] is old


def test_retraining_counts_newly_available_outcomes_not_old_holdout_dates(cfg,store,monkeypatch):
    import stox.models as m
    from types import SimpleNamespace
    cfg.horizons=(30,);cfg.min_new_labels=1
    store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',('old',30,'2026-04-01T00:00:00Z','champion','old.joblib','{}'));store.db.commit()
    old=SimpleNamespace(columns=['momentum_20'],model_id='old',metadata={'holdout_end':'2025-10-01','history_start':cfg.history_start,'model_design_version':4})
    monkeypatch.setattr(m.joblib,'load',lambda p:old)
    def fail(*args):raise AssertionError('Old outcomes must not count as newly matured labels')
    monkeypatch.setattr(m,'train_horizon',fail)
    labels=pd.DataFrame({'horizon':[30],'label_end':['2026-03-20'],'label_available_at':['2026-03-20T20:00:00Z'],'momentum_20':[.1]})
    assert m.registry_train(labels,cfg,store,stamp='2026-05-02T00:00:00Z')[30] is old


def test_trial_without_settlements_expires_without_promotion(store,cfg):
    register(store,'new','old',20,'2024-01-01T00:00:00Z',cfg)
    store.db.execute('INSERT INTO trial_forecasts VALUES(?,?,?,?,?,?,?,?,?,?)',('new','ABC','2024-01-02','2024-01-22','2024-01-01T00:00:00Z',.6,.01,.6,.01,20));store.db.commit()
    assess(store,cfg,'2024-01-03T00:00:00Z')
    assert active(store,20)
    assess(store,cfg,'2026-01-01T00:00:00Z')
    assert summary(store)[0]['status']=='insufficient'
    assert summary(store)[0]['diagnostics']['settled_coverage']==0
