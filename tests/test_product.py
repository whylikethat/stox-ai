"""Product contracts: research is visible and durable independently of validation."""
import copy
import json
import sqlite3
import pandas as pd
import pytest
from stox.storage import Store,SCHEMA
from stox.security import SecurityMaster
from stox.ingestion import Ingestor
from stox.screening import select_universe
from stox.ranking import consistency,leaderboards,forecast_rows
from stox.predictions import issue,settle,performance
from stox.models import validation_diagnostics
from stox.reporting import terminal,markdown,html_report,cleanup_reports
from stox.cli import main
from stox.providers.http import ProviderError
from test_security_master import asset

STAMP='2025-06-06T22:00:00+00:00'

class RecentAPI:
    def __init__(self,calendar):
        self.calendar=calendar;self.calls=[];self.interrupt=False
    def bars(self,refs,start,end):
        self.calls.append(([r.ticker for r in refs],start,end))
        if self.interrupt and len(self.calls)==2:
            raise KeyboardInterrupt()
        out={}
        for ref in refs:
            symbol=ref.ticker
            price=2 if symbol=='PENNY' else 100
            volume=10 if symbol=='ILLIQ' else 2_000_000
            out[symbol]=[{'t':self.calendar.open(s).isoformat(),'o':price,'c':price,'h':price+1,'l':price-1,'v':volume} for s in self.calendar.sessions(start,end[:10])]
        yield out


def prepare_screen(cfg,store,calendar):
    cfg.autonomous_universe=True;cfg.universe_size=1;cfg.screen_batch_size=2
    assets=[asset(s) for s in ('SPY','QQQ','AAA','BBB','PENNY','ILLIQ','HELD','WATCH','MICRO')]
    assets += [asset('OTC',exchange='OTC'),asset('LEV',name='Bull 3X ETF'),asset('09175M861')]
    assets[-4]['market_cap']=100_000_000  # MICRO
    master=SecurityMaster(store);master.refresh(assets,STAMP)
    with store.transaction():
        store.db.execute("INSERT INTO holdings(symbol,purchased,price) VALUES('HELD','2025-01-01',100)")
        store.db.execute("INSERT INTO watchlist VALUES('WATCH',?)",(STAMP,))
    api=RecentAPI(calendar);ing=Ingestor(cfg,store,calendar,api)
    refs=master.requests(cfg,discovery=True)
    return master,api,ing,refs


def test_two_stage_batched_screen_and_history_selection(cfg,store,calendar):
    master,api,ing,refs=prepare_screen(cfg,store,calendar)
    selected=select_universe(ing,master,refs,'2025-06-06','2025-06-06T23:59:59Z',STAMP)
    assert {r.ticker for r in selected}=={'AAA','SPY','QQQ','HELD','WATCH'}
    assert all(start>'2025-01-01' and len(symbols)<=2 for symbols,start,end in api.calls)
    assert not any(s in ('OTC','LEV','09175M861') for symbols,_,_ in api.calls for s in symbols)
    assert not list((cfg.root/'warehouse').rglob('*.parquet'))
    api.calls.clear()
    assert select_universe(ing,master,refs,'2025-06-06','2025-06-06T23:59:59Z',STAMP)==selected
    assert not api.calls
    cfg.history_start='2016-01-01'
    ing.bars(selected,master,'2025-06-06','2025-06-06T23:59:59Z',STAMP,[])
    assert {s for symbols,_,_ in api.calls for s in symbols}=={r.ticker for r in selected}
    assert all(start=='2016-01-01' for _,start,_ in api.calls)
    assert [r[0] for r in store.db.execute('SELECT symbol FROM watchlist')]==['WATCH']


def test_screen_interrupt_resumes_batches(cfg,store,calendar):
    master,api,ing,refs=prepare_screen(cfg,store,calendar)
    api.interrupt=True
    with pytest.raises(KeyboardInterrupt):
        select_universe(ing,master,refs,'2025-06-06','2025-06-06T23:59:59Z',STAMP)
    completed=set(api.calls[0][0]);api.calls.clear();api.interrupt=False
    select_universe(ing,master,refs,'2025-06-06','2025-06-06T23:59:59Z',STAMP)
    assert completed.isdisjoint({s for symbols,_,_ in api.calls for s in symbols})


def rows():
    return [dict(symbol='TEST',horizon=h,p_gain=.71,expected_return=-.0254,median_return=-.0068,
                 p_loss_5=.1,p_loss_10=.061,p_loss_20=.02,qualified=False,model_validated=False,
                 model_id='m',session='2025-01-03',probability_resolution=.02,model_agreement='high',
                 consistency_status='conflicting',quality_label='Research only',close=100,dollar_volume=30e6,
                 event_warning='Upcoming events unknown',exclusions=['forecast inconsistency'],primary_rank=1)
            for h in (20,30,60,90)]


def test_consistency_qcom_mu_and_visibility():
    assert consistency(.714,-.0254,[-.12,-.0068,.06])[0]=='conflicting'
    assert consistency(.674,.0259,[-.20,-.0519,.20])[0]=='conflicting'
    assert consistency(.60,.04,[-.10,.03,.20])[0]=='no detected conflict'
    candidates=rows()+[dict(rows()[1],symbol='CLEAN',consistency_status='no detected conflict',p_gain=.60)]
    primary,across=leaderboards(candidates)
    assert len(primary)==2 and len(across)==5 and primary[0]['symbol']=='CLEAN'
    assert not any(r['qualified'] for r in across)


def test_research_persistence_settlement_and_cohorts(store,calendar):
    forecasts=rows();forecasts[0]['qualified']=True
    meta={'event_cutoff':'2025-01-04T15:00:00Z','run_mode':'live','friction_bps':20}
    ids=issue(store,calendar,forecasts,'2025-01-04T15:00:00Z',meta)
    changed=copy.deepcopy(forecasts);changed[0]['p_gain']=.72
    issue(store,calendar,changed,'2025-01-04T16:00:00Z',meta)
    assert issue(store,calendar,forecasts,'2025-01-05T15:00:00Z',meta)==ids
    assert store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==2
    frame=pd.DataFrame([dict(symbol='TEST',session=s,open=100,high=111,low=99,close=110,volume=1e6,available_at=calendar.close(s).isoformat(),ingested_at=STAMP) for s in calendar.sessions('2025-01-06','2025-05-01')])
    store.put_bars('TEST',frame)
    assert settle(store,calendar,STAMP,20)['newly_settled']==8
    assert settle(store,calendar,STAMP,20)['newly_settled']==0
    perf=performance(store)
    assert set(perf['qualified']['horizons'])=={'20'}
    assert set(perf['research_only']['horizons'])=={'30','60','90'}
    assert set(perf['all_research']['horizons'])=={'20','30','60','90'}
    assert perf['research_only']['horizons']['30']['mean_return']==pytest.approx(.098)


def test_issue_atomic_rollback(store,calendar,monkeypatch):
    original=calendar.next_open;calls=[]
    def crash(t):
        calls.append(t)
        if len(calls)==2: raise KeyboardInterrupt()
        return original(t)
    monkeypatch.setattr(calendar,'next_open',crash)
    candidates=[rows()[0],dict(rows()[0],symbol='ZZZ')]
    with pytest.raises(KeyboardInterrupt): issue(store,calendar,candidates,STAMP,{'event_cutoff':STAMP})
    assert store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==0
    assert store.db.execute('SELECT count(*) FROM forecast_snapshots').fetchone()[0]==0
    monkeypatch.setattr(calendar,'next_open',original)
    assert len(issue(store,calendar,candidates,STAMP,{'event_cutoff':STAMP}))==2


def test_migration_retains_immutable_forecasts(cfg,calendar):
    s=Store(cfg.root)
    ids=issue(s,calendar,rows(),STAMP,{'event_cutoff':STAMP})
    before=[tuple(r) for r in s.db.execute('SELECT * FROM forecasts')]
    for table in ('forecast_snapshot_members','forecast_snapshots','universe_screen','watchlist'):
        s.db.execute('DROP TABLE '+table)
    s.db.execute('PRAGMA user_version=3');s.db.commit();s.close()
    s=Store(cfg.root)
    assert s.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA
    assert before==[tuple(r) for r in s.db.execute('SELECT * FROM forecasts')]
    assert issue(s,calendar,rows(),STAMP,{'event_cutoff':STAMP})==ids
    s.close()


def test_reports_zero_qualified_have_research():
    candidates=rows();primary,across=leaderboards(candidates)
    r=dict(metadata={},warnings=['Contradictory estimates'],primary_30d=primary,across_horizons=across,
           qualified_across_horizons=[],details=[],holdings=[],prospective={},backtests={},validation={},research_candidates=candidates)
    for text in (terminal(r),markdown(r),html_report(r,'')):
        assert 'TEST' in text and 'RESEARCH' in text and 'conflicting' in text
        assert 'validated' in text.lower()


def test_watchlist_is_user_managed(cfg,capsys):
    assert main(['--root',str(cfg.root),'watchlist','list'])==0
    assert '[]' in capsys.readouterr().out
    assert main(['--root',str(cfg.root),'watchlist','add','AAPL'])==0
    assert main(['--root',str(cfg.root),'watchlist','add','09175M861'])==1
    assert main(['--root',str(cfg.root),'watchlist','remove','AAPL'])==0


def test_validation_failure_reasons(cfg):
    m={'validated':False,'threshold':None,'evaluation':{'n':100,'blocks':2,'brier':.3,'base_brier':.2,'ece':.2,'buckets':[]}}
    d=validation_diagnostics(m,cfg)
    assert len(d['failure_reasons'])==4 and d['learned_threshold'] is None


def test_symbol_dedup_when_other_symbol_changes(store,calendar):
    a=rows();b=[dict(r,symbol='OTHER') for r in rows()]
    meta={'event_cutoff':STAMP,'run_mode':'live'}
    first=issue(store,calendar,a+b,STAMP,meta)
    b[0]['p_gain']=.72
    second=issue(store,calendar,a+b,'2025-06-06T23:00:00Z',meta)
    assert first[1]==second[1]  # TEST keeps its original entry/issuance
    assert store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==3


def test_contradiction_blocks_qualification_without_changing_values(cfg):
    import numpy as np
    from types import SimpleNamespace
    frame=pd.DataFrame([dict(symbol='QCOM',session='2025-06-06',close=100,dollar_volume=100e6,
                             history_count=1000,missing_recent=0,volatility=.2,drawdown=-.1)])
    bucket={'bucket':7,'n':1000,'blocks':30,'interval':[.60,.82],'probability':.714,'win_rate':.714}
    model=SimpleNamespace(committee=None,model_id='test',algorithm='logistic',metadata={
        'validated':True,'threshold':.6,'family':'price','evaluation':{'buckets':[bucket],'interval_80_coverage':.8}})
    model.predict=lambda f:(np.array([[.99,.939,.90,.714,.65,.55]]),np.array([-.0254]),np.array([[-.1,-.0068,.2]]))
    output=forecast_rows(frame,[{**asset('QCOM'),'security_type':'common','queryable':True}],{30:model},cfg,'2025-06-06')[0]
    assert not output['qualified'] and output['consistency_status']=='conflicting'
    assert output['p_gain']==.714 and output['expected_return']==-.0254 and output['median_return']==-.0068
    assert any('inconsistency' in r for r in output['exclusions'])


def test_screen_updates_only_recent_overlap(cfg,store,calendar):
    master,api,ing,refs=prepare_screen(cfg,store,calendar)
    select_universe(ing,master,refs,'2025-06-06','2025-06-06T23:59:59Z',STAMP)
    api.calls.clear()
    select_universe(ing,master,refs,'2025-06-09','2025-06-09T23:59:59Z','2025-06-09T23:59:59Z')
    assert all(start=='2025-06-03' for _,start,_ in api.calls)
    assert all(json.loads(r[0])['rows']>=20 for r in store.db.execute('SELECT payload FROM universe_screen'))


def test_news_budget_retains_cursor(cfg,store,calendar):
    from test_bootstrap_resume import Paged
    api=Paged(calendar,0)
    def pages(feed,start,end,cursor=None,snapshot=None,symbols=None):
        return [{'id':cursor or 'first','created_at':'2025-01-01T12:00:00Z','headline':'test'}],str(int(cursor or '0')+1)
    api.event_page=pages;cfg.news_pages_per_run=2
    ing=Ingestor(cfg,store,calendar,api)
    ing.events('news',SecurityMaster(store),'2025-01-07T22:00:00Z','2025-01-07')
    job=store.db.execute("SELECT * FROM feed_jobs WHERE scope='news:lookback:90'").fetchone()
    assert job['cursor']=='2' and job['status']=='running' and store.checkpoint('news') is None
    ing.events('news',SecurityMaster(store),'2025-01-07T22:01:00Z','2025-01-07')
    assert store.db.execute("SELECT cursor FROM feed_jobs WHERE scope='news:lookback:90'").fetchone()[0]=='4'
