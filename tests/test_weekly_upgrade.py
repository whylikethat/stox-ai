import copy,json
import numpy as np
import pandas as pd
from stox.ranking import rank
from stox.reporting import html_report,compare_snapshots,comparison_snapshot,current_provider_health,write_reports
from stox.models import ForecastModel,THRESHOLDS
from stox.features import market_features,ADVANCED_PRICE,FAMILIES,enrich


def candidate(symbol,p=.7,expected=.03,risk=.05,horizon=30,**kw):
    return dict(symbol=symbol,horizon=horizon,rank=1,p_gain=p,expected_return=expected,median_return=.02,
                p_loss_5=.1,p_loss_10=risk,p_loss_20=.02,qualified=False,model_agreement='high',
                consistency_status='no detected conflict',probability_resolution=1.,session='2026-10-09',**kw)


def report(rows):
    return dict(run_id='test',metadata={'run_mode':'live','provider_health':[{'provider':'security-request:X','status':'INACTIVE','detail':'RAW_SENTINEL'*10000}]},
                warnings=[],primary_30d=rows,across_horizons=rows,by_horizon={str(h):rows for h in (20,30,60,90)},
                research_candidates=[dict(r,raw='RAW_SENTINEL'*10000) for r in rows],details=[{'symbol':'X','debug':'RAW_SENTINEL'}],holdings=[],prospective={},backtests={},validation={})


def test_probability_before_upside_and_tail_before_expected():
    rows=[candidate('BWET',.504,.249,.496),candidate('BETTER',.68,.04,.04)]
    assert rank(rows)[0]['symbol']=='BETTER'
    assert rank([candidate('RISK',.68,.3,.4),candidate('SAFE',.68,.02,.02)])[0]['symbol']=='SAFE'
    assert rank(rows)==rank(list(reversed(rows)))


def test_html_preserves_tables_without_machine_payload(tmp_path):
    r=report([candidate('ABC')]); output=html_report(r,'')
    assert len(output.encode())<100000
    assert '<pre>' not in output and '<details>' not in output and 'RAW_SENTINEL' not in output
    for text in ('Primary 30D','Best Across All Horizons','Top 3 research highlights','Strict validated opportunities','20D research — Top 20','30D research — Top 20','60D research — Top 20','90D research — Top 20'):
        assert text in output
    for column in ('Rank','Security','Horizon','P(gain)','Expected net','Loss &gt;10%','Median','Agreement','Consistency','Status'):
        assert '<th>'+column+'</th>' in output
    assert '70.0%' in output
    r['details']=[]
    path=write_reports(tmp_path,r)
    assert 'RAW_SENTINEL' in (path/'report.json').read_text()
    assert 'RAW_SENTINEL' not in (path/'report.html').read_text()


def test_rank_changes_new_dropped_unchanged():
    old=comparison_snapshot(report([candidate('A'),candidate('B')]))
    new=comparison_snapshot(report([candidate('A'),candidate('C')]))
    result=compare_snapshots(new,old)['tables']['primary_30d']
    assert {r['symbol']:r['status'] for r in result}=={'A':'UNCHANGED','C':'NEW','B':'DROPPED'}
    assert result[0]['p_gain_change']==0


def test_current_health_excludes_stale_security_events():
    rows=[{'provider':'security-request:AAPL','status':'INACTIVE'},{'provider':'news','status':'PASS','updated_at':'2026-10-11'}]
    assert current_provider_health(rows)==rows[1:]


def test_coherent_distribution_matches_probabilities():
    model=ForecastModel('logistic',['x'],30,'coherent')
    # Every support belongs to the same interval as its mass, including both tails.
    model.distribution_support=np.repeat([-.3,-.15,-.07,-.02,.01,.035,.12],41)
    p=np.array([[.99,.95,.9,.7,.5,.2],[.8,.7,.6,.3,.2,.1]])
    mean,q=model.coherent_summary(p)
    assert q[0,1]>0 and q[1,1]<0
    assert np.all(np.diff(q,axis=1)>=0)
    masses=np.diff(np.c_[np.ones(2),p,np.zeros(2)]*-1,axis=1)
    weights=np.repeat(masses/41,41,axis=1)
    for i,t in enumerate(THRESHOLDS):
        np.testing.assert_allclose(weights[:,model.distribution_support>t].sum(axis=1),p[:,i])
    np.testing.assert_allclose(mean,weights@model.distribution_support)


def test_advanced_feature_prefix_causal_and_new_session(calendar):
    days=calendar.sessions('2023-01-03','2025-01-03')
    bars=pd.DataFrame({'session':days,'close':100+np.arange(len(days))*.1,'open':100+np.arange(len(days))*.1,'volume':np.full(len(days),1e6)})
    first=market_features(bars,[],calendar)
    changed=bars.copy(); changed.loc[changed.index[-1],'close']*=1.2
    second=market_features(changed,[],calendar)
    pd.testing.assert_frame_equal(first.iloc[:-1],second.iloc[:-1])
    assert first.iloc[-1].momentum_10!=second.iloc[-1].momentum_10
    assert set(ADVANCED_PRICE)<=set(first)


def test_optional_missing_credentials_and_future_observation(cfg,store):
    frame=pd.DataFrame({'symbol':['A','A'],'issue_at':['2025-01-01T00:00:00Z','2025-03-01T00:00:00Z']})
    cfg.enable_analyst_signals=True
    store.record('external_analyst','a',{'symbol':'A','available_at':'2024-12-01T00:00:00Z','observed_at':'2025-02-01T00:00:00Z','source_url':'https://example.test/licensed','license_confirmed':True,'values':{'analyst_eps_revision_30':.1}},'2025-02-01T00:00:00Z')
    enriched=enrich(frame,store,cfg)
    assert np.isnan(enriched.iloc[0].analyst_eps_revision_30)
    assert enriched.iloc[1].analyst_eps_revision_30==.1
    assert enriched.options_iv30.isna().all()


def test_deterministic_model_inference_reacts_to_evidence():
    from stox.models import BinaryModel,Sigmoid
    from threadpoolctl import threadpool_limits
    x=np.linspace(-3,3,500).reshape(-1,1);y=(x[:,0]>0).astype(int)
    with threadpool_limits(limits=1):
        model=BinaryModel('logistic').fit(x,y)
        cal=Sigmoid().fit(model.predict(x),y)
        unchanged=np.array([[-1.],[1.]])
        a=cal.predict(model.predict(unchanged));b=cal.predict(model.predict(unchanged))
        np.testing.assert_array_equal(a,b)
        changed=cal.predict(model.predict(np.array([[2.],[-2.]])))
    before=rank([candidate('A',a[0]),candidate('B',a[1])])
    after=rank([candidate('A',changed[0]),candidate('B',changed[1])])
    assert before[0]['symbol']=='B' and after[0]['symbol']=='A'


def test_news_features_causal(cfg,store):
    frame=pd.DataFrame({'symbol':['A','A'],'issue_at':['2025-02-02T00:00:00Z','2025-02-04T00:00:00Z']})
    store.record('news','old',{'symbols':['A'],'created_at':'2025-01-01T00:00:00Z','headline':'baseline'},'2025-01-01T00:00:00Z')
    first=enrich(frame,store,cfg)
    store.record('news','new',{'symbols':['A'],'created_at':'2025-02-03T00:00:00Z','headline':'FDA investigation financing'},'2025-02-03T00:00:00Z')
    second=enrich(frame,store,cfg)
    pd.testing.assert_series_equal(first.iloc[0],second.iloc[0])
    assert second.iloc[1].news_regulatory==1 and second.iloc[1].news_financing==1


def test_indexed_evidence_matches_full_scan(cfg,store):
    from stox.reporting import evidence,index_evidence
    snapshots={'news':[{'symbols':['ABC'],'headline':'test'},{'symbols':['XYZ'],'headline':'other'}],
               'filings':[{'symbol':'ABC'}],'facts':[], 'earnings':[],
               'actions':[{'resolved_tickers':['ABC'],'action_type':'cash_dividends'},{'target_symbol':'ABC','action_type':'stock_mergers'}],
               'disclosure_documents':[],'disclosure_transactions':[]}
    assert evidence(store,'ABC','2026-10-11T00:00:00Z',cfg,snapshots)==evidence(store,'ABC','2026-10-11T00:00:00Z',cfg,index_evidence(snapshots))


def test_inference_skips_labels_only_with_compatible_recent_champions(cfg,store):
    from stox.models import needs_training_labels
    from stox.storage import encode
    frame=pd.DataFrame({'momentum_20':[.1]})
    assert needs_training_labels(cfg,store,frame,'2026-10-11T00:00:00Z')
    for h in cfg.horizons:
        with store.transaction():
            store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',(str(h),h,'2026-10-10T00:00:00Z','champion','unused.joblib',encode({'history_start':cfg.history_start,'feature_columns':['momentum_20']})))
    assert not needs_training_labels(cfg,store,frame,'2026-10-11T00:00:00Z')
    assert needs_training_labels(cfg,store,frame,'2026-11-20T00:00:00Z')
    assert needs_training_labels(cfg,store,frame,'2026-10-11T00:00:00Z',force=True)
    assert needs_training_labels(cfg,store,pd.DataFrame({'momentum_20':[np.nan]}),'2026-10-11T00:00:00Z')


def test_batched_explanation_preserves_reference_effects():
    model=ForecastModel('logistic',['a','b'],30)
    model.reference=np.array([0.,0.])
    def predict(frame):
        p=1/(1+np.exp(-(frame.a+2*frame.b).to_numpy()))
        return np.repeat(p[:,None],6,axis=1),p,np.repeat(p[:,None],3,axis=1)
    model.predict=predict
    row={'a':1.,'b':-.5}
    result={r['feature']:r['probability_change_from_reference'] for r in model.explain(row)}
    original=predict(pd.DataFrame([row]))[0][0,3]
    for name in ('a','b'):
        altered={**row,name:0.}
        assert np.isclose(result[name],original-predict(pd.DataFrame([altered]))[0][0,3])
