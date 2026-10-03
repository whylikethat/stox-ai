import json
import sqlite3
import pandas as pd
import pytest
from stox.actions import total_return,UnresolvedAction,adjusted_history
from stox.config import Config
from stox.storage import Store
from stox.predictions import issue,settle,performance
from stox.models import temporal_split,wilson
from stox.ranking import rank
from stox.universe import classify,eligible
from stox.features import asof_values,market_features
from stox.holdings import add,review


def test_config_paths_and_secret_redaction(tmp_path,monkeypatch):
    p=tmp_path/'config.toml'
    p.write_text('[stox]\nroot="external/data"\nhorizons=[20,30,60,90]\n')
    monkeypatch.setenv('ALPACA_API_KEY','secret-test')
    c=Config.load(str(p))
    assert c.root==tmp_path/'external/data'
    assert 'secret-test' not in repr(c)
    assert 'secrets' not in c.public()


def test_calendar_weekend_holiday_early_close(calendar):
    assert calendar.next_open('2025-07-03T18:00:00Z')=='2025-07-07'
    assert calendar.close('2025-07-03').hour==17
    assert calendar.completed('2025-07-04T20:00:00Z')=='2025-07-03'
    assert calendar.settle('2025-07-01',30)=='2025-07-31'
    assert calendar.settle('2025-07-01',20)=='2025-07-21'
    with pytest.raises(ValueError):
        calendar.sip_end('2025-07-03T17:05:00Z')
    assert calendar.next_open('2025-07-07T13:30:00Z')=='2025-07-08'


def test_total_return_split_dividend_and_entry_exdate():
    actions=[{'action_type':'forward_splits','ex_date':'2025-01-10','old_rate':1,'new_rate':2},
             {'action_type':'cash_dividends','ex_date':'2025-01-15','rate':1}]
    assert total_return(100,55,'2025-01-01','2025-01-31',actions,20)==pytest.approx(.118)
    assert total_return(50,55,'2025-01-15','2025-01-31',actions,0)==pytest.approx(.1)
    with pytest.raises(UnresolvedAction):
        total_return(100,55,'2025-01-01','2025-01-31',[{'action_type':'spin_offs','ex_date':'2025-01-12'}])


def test_checkpoint_revision_and_budget(store):
    store.record('news','1',{'headline':'first'},'2025-01-01T00:00:00Z')
    store.record('news','1',{'headline':'revised'},'2025-01-02T00:00:00Z')
    store.record('news','1',{'headline':'revised'},'2025-01-02T00:00:00Z')
    assert store.db.execute('SELECT count(*) FROM records').fetchone()[0]==2
    assert store.records('news','2025-01-01T12:00:00Z')[0]['headline']=='first'
    assert store.budget('test',1)
    assert not store.budget('test',1)
    assert store.checkpoint('x') is None
    store.advance('x','2025-01-01')
    assert store.checkpoint('x')=='2025-01-01'


def test_no_lookahead_macro_revisions():
    rows=[{'date':'2024-12-01','value':1,'available_at':'2025-01-02T00:00:00Z'},
          {'date':'2024-12-01','value':2,'available_at':'2025-02-01T00:00:00Z'},
          {'date':'2024-11-01','value':8,'available_at':'2025-02-02T00:00:00Z'}]
    v=asof_values(pd.to_datetime(['2025-01-10T00:00:00Z','2025-02-10T00:00:00Z']),rows,'value',period='date')
    assert list(v)==[1,2]


def test_temporal_purge():
    f=pd.DataFrame({'session':['2025-01-01','2025-01-02','2025-03-01'], 'label_end':['2025-01-31','2025-03-05','2025-03-31']})
    train,test=temporal_split(f,'2025-03-01')
    assert len(train)==1
    assert len(test)==1
    assert train.label_end.max()<'2025-02-24'
    assert wilson(9,10)[0]<.9


def test_rank_ties():
    rows=[{'symbol':'A','horizon':30,'p_gain':.94,'expected_return':.02,'probability_resolution':.02,'p_loss_20':.01},
          {'symbol':'B','horizon':60,'p_gain':.88,'expected_return':.08,'probability_resolution':.02,'p_loss_20':.01}]
    assert rank(rows)[0]['symbol']=='A'
    rows[1]['p_gain']=.94
    assert rank(rows)[0]['symbol']=='B'


def test_security_filters(cfg):
    a={'tradable':True,'queryable':True,'class':'us_equity','name':'Normal ETF','exchange':'ARCA','status':'active'}
    assert classify(a)=='etf'
    assert classify({**a,'name':'Bull 3X ETF'})=='excluded'
    assert classify({**a,'name':'Company Warrants'})=='excluded'
    assert eligible(a,{'close':10,'dollar_volume':1e6,'history_count':300,'missing_recent':0},cfg)
    assert not eligible(a,{'close':10,'dollar_volume':50e6,'history_count':300,'missing_recent':0},cfg)


def test_forecast_immutable_entry_and_independent_settlement(store,calendar):
    rows=[{'symbol':'DEMO','horizon':h,'qualified':True,'p_gain':.75,'primary_rank':1 if h==30 else None} for h in (20,30,60,90)]
    meta={'event_cutoff':'2025-01-04T15:00:00Z'}
    ids=issue(store,calendar,rows,'2025-01-04T15:00:00Z',meta)
    assert issue(store,calendar,rows,'2025-01-04T15:00:00Z',meta)==ids
    assert store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==1
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute('UPDATE forecasts SET symbol="BAD"')
    store.db.rollback()
    frame=pd.DataFrame([{'session':s,'symbol':'DEMO','open':100,'close':110,'high':111,'low':99,'volume':1e6,'available_at':calendar.close(s).isoformat(),'ingested_at':'2025-02-07T22:00:00Z'} for s in calendar.sessions('2025-01-06','2025-02-07')])
    store.put_bars('DEMO',frame)
    result=settle(store,calendar,'2025-02-07T22:00:00Z',20)
    assert result['newly_settled']==2
    assert settle(store,calendar,'2025-02-07T22:00:00Z',20)['newly_settled']==0
    assert store.db.execute('SELECT price FROM entries').fetchone()[0]==100
    assert store.db.execute('SELECT count(*) FROM outcomes').fetchone()[0]==2
    assert performance(store)['horizons']['30']['mean_return']==pytest.approx(.098)


def test_holdings_and_disk_limits(store,cfg):
    hid=add(store,'AAPL','2025-01-01',100,10)
    r=review(store,[],'test')[0]
    assert r['status']=='WARNING'
    assert r['id']==hid
    with pytest.raises(ValueError):
        add(store,'X','2025-01-01',-1)
    with pytest.raises(RuntimeError):
        store.storage_check(0,0)


def test_schema_rejects_newer(store,cfg):
    store.db.execute('PRAGMA user_version=999')
    store.db.commit()
    with pytest.raises(RuntimeError):
        Store(cfg.root)


def test_pending_entry_before_next_open(store,calendar):
    rows=[{'symbol':'X','horizon':30,'qualified':True,'p_gain':.8}]
    issue(store,calendar,rows,'2025-01-04T15:00:00Z',{'event_cutoff':'2025-01-04T15:00:00Z'})
    result=settle(store,calendar,'2025-01-04T15:00:00Z',20)
    assert result['pending_entries']==1
    assert store.db.execute('SELECT count(*) FROM entries').fetchone()[0]==0


def test_only_qualified_horizons_enter_primary_metrics(store,calendar):
    rows=[{'symbol':'X','horizon':30,'qualified':False,'p_gain':.8}]
    assert issue(store,calendar,rows,'2025-01-04T15:00:00Z',{'event_cutoff':'2025-01-04T15:00:00Z'})==[]
    assert performance(store)['horizons']=={}


def test_mutation_lock(store):
    other=Store(store.root)
    try:
        with store.lock():
            with pytest.raises(RuntimeError):
                with other.lock():
                    pass
    finally:
        other.close()


def test_corporate_action_does_not_change_earlier_features(cfg,calendar):
    from stox.demo import seed
    seed(cfg,end='2016-12-30')
    s=Store(cfg.root)
    bars=s.bars('DEMOA')
    first=market_features(bars,[],calendar)
    action={'action_type':'cash_dividends','ex_date':'2016-12-01','rate':1}
    second=market_features(bars,[action],calendar)
    pd.testing.assert_frame_equal(first[first.session<'2016-12-01'],second[second.session<'2016-12-01'])
    s.close()
