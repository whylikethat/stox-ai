"""Offline fault-injection, legacy upgrade, namespace and transaction-cost regressions."""
import copy
import json
import sqlite3
import time
from pathlib import Path
import pytest
from stox.storage import Store, SCHEMA, digest, encode
from stox.security import SecurityMaster
from stox.ingestion import Ingestor
from stox.progress import Progress
from stox.streams import reuse_legacy_actions
from stox.providers.http import ProviderError
from stox.diagnostics import status, diagnose
from test_security_master import FixtureAlpaca, asset

STAMP='2025-01-07T22:00:00+00:00'


def events(n):
    return [{'id':f'action-{i}','symbol':'SPY','cusip':'09175M861','ex_date':'2025-01-03',
             'action_type':'cash_dividends','rate':0.1,'currency':'USD'} for i in range(n)]


class Paged(FixtureAlpaca):
    def __init__(self,calendar,n=2500,page_size=1000):
        super().__init__(calendar,[asset('SPY',name='SPDR S&P 500 ETF Trust'),
                                   asset('QQQ',name='Invesco QQQ Trust, Series 1'),asset('AAPL'),asset('MSFT')])
        self.rows=events(n)
        self.page_size=page_size
        self.page_calls=[]
        self.fail_cursor=None
        self.fail_once=False
        self.expired=False

    def event_page(self,feed,start,end,cursor=None,snapshot=None):
        self.page_calls.append((feed,start,end,cursor,snapshot))
        if feed=='news': return [],None
        if self.fail_once and cursor==self.fail_cursor:
            self.fail_once=False
            raise ProviderError('temporary network loss')
        if self.expired and cursor:
            self.expired=False
            raise ProviderError('expired page token',status_code=400)
        candidates=[r for r in self.rows if start<=r['ex_date']<=end]
        offset=int(cursor or 0)
        stop=offset+self.page_size
        return copy.deepcopy(candidates[offset:stop]),str(stop) if stop<len(candidates) else None


def ingestor(cfg,store,calendar,api):
    cfg.history_start='2025-01-01'
    ing=Ingestor(cfg,store,calendar,api)
    ing.optional=lambda *args:None
    return ing


def counts(store):
    return tuple(store.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                 for table in ('records','security_identifiers','action_sources'))


def test_page_resume_preserves_completed_bars_and_raw_provenance(cfg,store,calendar):
    api=Paged(calendar)
    api.fail_cursor='1000';api.fail_once=True
    ing=ingestor(cfg,store,calendar,api)
    with pytest.raises(ProviderError): ing.run(STAMP)
    assert store.checkpoint('actions') is None
    job=store.db.execute("SELECT * FROM feed_jobs WHERE scope='actions'").fetchone()
    assert job['cursor']=='1000' and job['processed']==1000
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==1000
    assert set(api.calls)=={'SPY','QQQ','AAPL','MSFT'}
    api.calls.clear();api.page_calls.clear()
    ing.run(STAMP)
    assert api.calls==[]
    assert api.page_calls[0][3]=='1000'
    assert store.checkpoint('actions')==STAMP
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==2500
    assert '09175M861' not in api.calls
    before=counts(store)
    api.page_calls.clear();ing.run(STAMP)
    assert api.page_calls==[]
    assert before==counts(store)
    assert store.db.execute("SELECT 1 FROM security_identifiers WHERE kind='cusip' AND value='09175M861'").fetchone()


def test_mid_page_interrupt_rolls_back_identifiers_records_and_cursor(cfg,store,calendar,monkeypatch):
    api=Paged(calendar,30,10)
    ing=ingestor(cfg,store,calendar,api)
    original=SecurityMaster.annotate_action
    def crash(self,row):
        result=original(self,row)
        if row['id']=='action-15': raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(SecurityMaster,'annotate_action',crash)
    with pytest.raises(KeyboardInterrupt): ing.run(STAMP)
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==10
    assert not store.db.execute("SELECT 1 FROM security_identifiers WHERE entity_id='corporate-action:action-15'").fetchone()
    assert store.db.execute("SELECT cursor FROM feed_jobs WHERE scope='actions'").fetchone()[0]=='10'
    monkeypatch.setattr(SecurityMaster,'annotate_action',original)
    ing.run(STAMP)
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==30


def test_large_fixture_commit_count_scales_with_pages(cfg,store,calendar):
    api=Paged(calendar,10000,1000)
    # Duplicate provider records within and across pages must not multiply state.
    api.rows+=copy.deepcopy(api.rows[:1000])
    ing=ingestor(cfg,store,calendar,api)
    master=SecurityMaster(store);master.refresh(api.assets(),STAMP)
    trace=[];store.db.set_trace_callback(lambda sql: trace.append(sql) if sql=='COMMIT' else None)
    started=time.monotonic()
    with ing.progress.stage('corporate-actions'):
        ing.events('actions',master,STAMP,'2025-01-07')
    elapsed=time.monotonic()-started
    store.db.set_trace_callback(None)
    commits=len(trace)
    assert commits<=11+6  # eleven pages plus job/stage lifecycle, never per identifier
    assert store.db.execute("PRAGMA synchronous").fetchone()[0]==2  # FULL durability retained
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==10000
    assert store.db.execute("SELECT count(*) FROM records WHERE kind='actions'").fetchone()[0]==10000
    assert store.db.execute("SELECT count(*) FROM security_identifiers WHERE source='alpaca_corporate_actions'").fetchone()[0]==30000
    print(f'BENCHMARK: 11000 input / 10000 unique actions; {commits} commits; {elapsed:.3f}s; 30000 typed IDs')
    # No wall-clock gate: external-drive performance differs. The transaction bound is the gate.


def test_legacy_upgrade_indexes_existing_rows_without_rewriting(cfg,store,calendar):
    master=SecurityMaster(store);api=Paged(calendar,1500)
    master.refresh(api.assets(),STAMP)
    old='2025-01-04T20:00:00+00:00'
    with store.transaction():
        for row in api.rows:
            store.record('actions',row['id'],master.annotate_action(row),old,old)
        store.advance('bars:SPY','2025-01-07')
        # Exact v2 tables are retained. Drop only new fixture metadata to simulate pre-upgrade.
        for table in ('feed_jobs','feed_pages','action_sources','stages','runtime_meta','bar_state'):
            store.db.execute('DROP TABLE '+table)
        for index in ('asset_identifier_lookup','runs_recent','runs_success'):
            store.db.execute('DROP INDEX '+index)
        store.db.execute('PRAGMA user_version=2')
    before=store.db.execute("SELECT record_id,revision,available_at,ingested_at FROM records WHERE kind='actions'").fetchall()
    store.close()
    upgraded=Store(cfg.root)
    try:
        assert upgraded.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA
        progress=Progress(upgraded,'upgrade')
        with progress.stage('legacy-action-index'):
            reuse_legacy_actions(upgraded,SecurityMaster(upgraded),progress,batch_size=100)
        after=upgraded.db.execute("SELECT record_id,revision,available_at,ingested_at FROM records WHERE kind='actions'").fetchall()
        assert [tuple(r) for r in before]==[tuple(r) for r in after]
        assert upgraded.checkpoint('actions') is None  # MAX(event date) does NOT certify completeness
        assert upgraded.checkpoint('bars:SPY')=='2025-01-07'
        ing=ingestor(cfg,upgraded,calendar,api)
        with ing.progress.stage('corporate-actions'):
            ing.events('actions',SecurityMaster(upgraded),STAMP,'2025-01-07')
        assert upgraded.db.execute("SELECT count(*) FROM records WHERE kind='actions'").fetchone()[0]==1500
        job=upgraded.db.execute("SELECT * FROM feed_jobs WHERE scope='actions'").fetchone()
        assert job['inserted']==0 and job['skipped']==1500
        n=counts(upgraded)
        upgraded.migrate()
        with progress.stage('legacy-action-index'):
            reuse_legacy_actions(upgraded,SecurityMaster(upgraded),progress)
        assert counts(upgraded)==n
    finally: upgraded.close()


def test_schema_upgrade_transaction_rolls_back_on_failure(cfg,store,monkeypatch):
    with store.transaction():
        store.db.execute('PRAGMA user_version=2')
        store.db.execute('DROP TABLE feed_jobs')
    original=Store._migrate_schema
    def fail(self):
        original(self)
        raise RuntimeError('injected migration failure')
    monkeypatch.setattr(Store,'_migrate_schema',fail)
    with pytest.raises(RuntimeError): store.migrate()
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2
    assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='feed_jobs'").fetchone()
    monkeypatch.setattr(Store,'_migrate_schema',original)
    store.migrate()
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA


def test_expired_cursor_replays_current_window_only(cfg,store,calendar):
    api=Paged(calendar,20,10)
    api.fail_cursor='10';api.fail_once=True
    ing=ingestor(cfg,store,calendar,api)
    cfg.history_start='2024-12-01'
    with pytest.raises(ProviderError): ing.run(STAMP)
    api.page_calls.clear();api.expired=True
    ing.run(STAMP)
    calls=[c for c in api.page_calls if c[0]=='actions']
    assert all(c[1]=='2025-01-01' for c in calls)
    assert [c[3] for c in calls]==['10',None,'10']
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==20


def test_known_identifiers_are_namespaced_not_global_poison(store):
    master=SecurityMaster(store)
    master.identifier('corporate-action:fake','alpaca_asset_id','QQQ','alpaca_corporate_actions')
    rows=[asset('SPY',name='SPDR S&P 500 ETF Trust'),asset('QQQ',name='Invesco QQQ Trust, Series 1'),asset('AAPL'),asset('MSFT')]
    rows += [asset('QQQ',id='historical-qqq',status='inactive')]
    master.refresh(rows,STAMP)
    for ticker in ('SPY','QQQ','AAPL','MSFT'):
        assert master.resolve(ticker).ticker==ticker
    n=store.db.execute("SELECT count(*) FROM security_identifiers WHERE role='current_ticker'").fetchone()[0]
    master.refresh(rows,'2025-01-08T22:00:00+00:00')
    assert store.db.execute("SELECT count(*) FROM security_identifiers WHERE role='current_ticker'").fetchone()[0]==n
    with pytest.raises(ValueError): master.resolve('09175M861')
    with pytest.raises(ValueError): master.resolve_identifier('alpaca_asset_id','QQQ')


def test_duplicate_snapshot_same_asset_is_not_ambiguous(store):
    master=SecurityMaster(store)
    a=asset('QQQ',name='Invesco QQQ Trust, Series 1')
    master.refresh([a,dict(a),dict(a,status='inactive')],STAMP)
    assert master.resolve('QQQ').alpaca_asset_id==a['id']


def test_status_large_fixture_has_bounded_sql_work_and_no_parquet(cfg,store,monkeypatch):
    with store.transaction():
        store.db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?)',
            [('news',str(i),'r',STAMP,STAMP,'{}') for i in range(50000)])
        store.db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',('run',STAMP,None,'running','{}'))
    monkeypatch.setattr(Store,'bars',lambda *a:pytest.fail('status must not read parquet'))
    monkeypatch.setattr(Store,'storage_check',lambda *a:pytest.fail('status must not walk data directories'))
    import stox.diagnostics as diagnostics
    original=diagnostics.reader
    ops=[]
    def bounded(root):
        db=original(root)
        def guard():
            ops.append(1)
            return len(ops)>100  # 10k VM opcodes; independent of record-table size
        db.set_progress_handler(guard,100)
        return db
    monkeypatch.setattr(diagnostics,'reader',bounded)
    with store.lock():
        result=status(cfg.root)
        assert result['writer_active'] and result['state']=='running'
    assert 'interrupted' in status(cfg.root)['state']
    assert len(ops)<100
    monkeypatch.setattr(diagnostics,'reader',original)
    report=diagnose(cfg.root,deep=True)
    assert report['table_rows']['records']==50000
    assert report['records_by_kind'][0]['provider_ids']==50000


def test_bootstrap_engine_interruption_resume_reports_and_second_run(cfg,calendar,monkeypatch):
    from stox.demo import seed
    from stox.engine import run
    import stox.ingestion as ingestion
    stamp=seed(cfg)
    cfg.history_start='2025-01-01'
    setup=Store(cfg.root)
    assets=setup.records('assets')
    with setup.transaction():
        setup.db.execute("DELETE FROM checkpoints WHERE scope IN ('actions','news')")
    setup.close()
    api=Paged(calendar,20,10)
    api.asset_rows=assets
    api.fail_cursor='10';api.fail_once=True
    monkeypatch.setattr(ingestion,'Alpaca',lambda *args:api)
    monkeypatch.setattr(ingestion.Ingestor,'optional',lambda *args:None)
    # Keep observations in this explicitly synthetic time domain.
    monkeypatch.setattr(ingestion,'now_iso',lambda:stamp)
    with pytest.raises(ProviderError): run(cfg,timestamp=stamp,synthetic=True)
    assert api.calls==[]
    check=Store(cfg.root)
    assert check.db.execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]=='failed'
    check.close()
    api.page_calls.clear()
    report,path=run(cfg,timestamp=stamp,synthetic=True)
    assert api.page_calls[0][3]=='10'
    assert api.calls==[]
    assert set(report['backtests'])=={'20','30','60','90'}
    assert (path/'report.html').exists()
    check=Store(cfg.root);before=counts(check);check.close()
    api.page_calls.clear()
    report2,path2=run(cfg,timestamp=stamp,synthetic=True)
    assert api.calls==[] and api.page_calls==[]
    assert report2['metadata']['model_ids']==report['metadata']['model_ids']
    check=Store(cfg.root)
    assert counts(check)==before
    assert check.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    check.close()


def test_changed_provider_payload_keeps_first_release_and_revision(cfg,store,calendar):
    api=Paged(calendar,1)
    ing=ingestor(cfg,store,calendar,api)
    ing.run(STAMP)
    old=store.db.execute("SELECT * FROM records WHERE kind='actions'").fetchone()
    api.rows[0]['rate']=0.2
    ing.run('2025-01-08T22:00:00+00:00')
    rows=store.db.execute("SELECT * FROM records WHERE kind='actions' ORDER BY rowid").fetchall()
    assert len(rows)==2
    assert tuple(old)==tuple(rows[0])
    assert json.loads(rows[1]['payload'])['rate']==0.2
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==2


def test_legacy_backfill_itself_resumes_without_rewriting(cfg,store,calendar,monkeypatch):
    api=Paged(calendar,50)
    master=SecurityMaster(store);master.refresh(api.assets(),STAMP)
    with store.transaction():
        for row in api.rows: store.record('actions',row['id'],master.annotate_action(row),STAMP)
    original=store.advance
    def fail(scope,value):
        if scope=='migration:action_sources' and int(value)>30: raise KeyboardInterrupt()
        original(scope,value)
    monkeypatch.setattr(store,'advance',fail)
    p=Progress(store,'upgrade')
    with pytest.raises(KeyboardInterrupt),p.stage('legacy-action-index'):
        reuse_legacy_actions(store,master,p,batch_size=10)
    checkpoint=int(store.checkpoint('migration:action_sources'))
    assert checkpoint<=30
    monkeypatch.setattr(store,'advance',original)
    with p.stage('legacy-action-index'):
        reuse_legacy_actions(store,master,p,batch_size=10)
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==50
    assert store.db.execute("SELECT count(*) FROM records WHERE kind='actions'").fetchone()[0]==50


def test_repeated_cursor_fails_without_advancing_checkpoint(cfg,store,calendar):
    api=Paged(calendar,20,10)
    original=api.event_page
    def repeated(feed,start,end,cursor=None,snapshot=None):
        rows,token=original(feed,start,end,cursor,snapshot)
        return (rows,cursor or token) if feed=='actions' else (rows,token)
    api.event_page=repeated
    ing=ingestor(cfg,store,calendar,api)
    with pytest.raises(ProviderError,match='repeated'): ing.run(STAMP)
    assert store.db.execute("SELECT cursor FROM feed_jobs WHERE scope='actions'").fetchone()[0]=='10'
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==10
    assert store.checkpoint('actions') is None


def test_namespaces_provider_id_and_closed_end_trust(store):
    master=SecurityMaster(store)
    master.refresh([asset('QQQ',name='Invesco QQQ Trust, Series 1'),asset('MSFT',provider_id='QQQ'),
                    asset('BAD',name='Leveraged Bull Trust, Series 1'),asset('UNKNOWN',name='Unknown Income Trust')],STAMP)
    assert master.resolve('QQQ').ticker=='QQQ'
    with pytest.raises(ValueError): master.resolve('BAD')
    with pytest.raises(ValueError): master.resolve('UNKNOWN')
    assert master.resolve_identifier('provider_id','QQQ').ticker=='MSFT'


def test_alpaca_event_page_exact_request_contract_and_news_boundary():
    from stox.providers.alpaca import Alpaca
    from test_providers import FakeHTTP
    h=FakeHTTP([{'corporate_actions':{'cash_dividends':[{'id':'one'}]},'next_page_token':'opaque'},
                {'news':[],'next_page_token':None}])
    api=Alpaca({'ALPACA_API_KEY':'fixture','ALPACA_API_SECRET':'fixture'},h)
    rows,token=api.event_page('actions','2025-01-01','2025-01-31','previous',STAMP)
    assert token=='opaque' and rows[0]['action_type']=='cash_dividends'
    assert h.calls[0][1]['params']=={'start':'2025-01-01','end':'2025-01-31','page_token':'previous','limit':1000,'sort':'asc'}
    api.event_page('news','2025-01-01','2025-01-07',None,STAMP)
    assert h.calls[1][1]['params']['end']==STAMP


def test_provider_failure_does_not_discard_old_page_on_new_day(cfg,store,calendar):
    api=Paged(calendar,20,10)
    ing=ingestor(cfg,store,calendar,api)
    api.fail_cursor='10';api.fail_once=True
    with pytest.raises(ProviderError): ing.run(STAMP)
    api.page_calls.clear()
    ing.run('2025-01-08T22:00:00+00:00')
    assert api.page_calls[0][3]=='10' and api.page_calls[0][4]==STAMP
    assert store.checkpoint('actions')=='2025-01-08T22:00:00+00:00'
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==20


def test_sec_completed_response_pages_reused_after_network_failure(cfg,store):
    from stox.providers.sec import SEC
    from test_providers import FakeHTTP
    submissions={'filings':{'recent':{'accessionNumber':[]},'files':[{'name':'old.json'}]}}
    h=FakeHTTP([submissions,{'accessionNumber':[]},ProviderError('network outage')])
    sec=SEC('Fixture fixture@example.com',h)
    with pytest.raises(ProviderError): sec.company('0000000001',store=store,snapshot='2025-01-07')
    h2=FakeHTTP([{'facts':{}}])
    assert SEC('Fixture fixture@example.com',h2).company('0000000001',store=store,snapshot='2025-01-07')==([],[])
    assert len(h2.calls)==1 and 'companyfacts' in h2.calls[0][0]


def test_fred_paged_offset_frozen_snapshot_and_transactional_resume(cfg,store,calendar,monkeypatch):
    import stox.ingestion as module
    from stox.providers.fred import FRED
    from test_providers import FakeHTTP
    cfg.macro_series=('DGS10',)
    cfg.secrets['FRED_API_KEY']='fixture'
    rows=[{'date':'2025-01-01','realtime_start':'2025-01-02','value':'3.0'}]
    h=FakeHTTP([{'count':2,'observations':rows},ProviderError('network interruption')])
    real=FRED
    monkeypatch.setattr(module,'FRED',lambda key:real(key,h))
    ing=Ingestor(cfg,store,calendar,Paged(calendar,0))
    ing.optional([],STAMP,[])
    assert store.checkpoint('fred:DGS10') is None
    assert store.checkpoint('fred:DGS10:offset')=='1'
    h2=FakeHTTP([{'count':2,'observations':[dict(rows[0],date='2025-01-02')]}])
    monkeypatch.setattr(module,'FRED',lambda key:real(key,h2))
    ing.optional([],STAMP,[])
    assert h2.calls[0][1]['params']['offset']==1
    assert h2.calls[0][1]['params']['realtime_end']=='2025-01-07'
    assert store.checkpoint('fred:DGS10')==STAMP
    assert store.db.execute("SELECT count(*) FROM records WHERE kind='macro'").fetchone()[0]==2
    assert store.checkpoint('fred:DGS10:offset') is None


def test_compact_preserves_records_and_refuses_active_writer(cfg,store):
    from stox.diagnostics import compact
    store.record('actions','retain',{'id':'retain','rate':1},STAMP)
    with store.lock():
        with pytest.raises(RuntimeError,match='Another STOX'):
            compact(cfg.root)
    result=compact(cfg.root)
    assert result['deleted_records']==0 and result['integrity_check']==['ok']
    assert store.records('actions')[0]['id']=='retain'


def test_page_receipts_and_data_rollback_together_on_sql_failure(cfg,store,calendar,monkeypatch):
    api=Paged(calendar,20,10)
    ing=ingestor(cfg,store,calendar,api)
    original=ing.progress.update
    def fail(**kw):
        if kw.get('pages')==2: raise RuntimeError('failure after data insertion before commit')
        original(**kw)
    monkeypatch.setattr(ing.progress,'update',fail)
    with pytest.raises(RuntimeError,match='after data'): ing.run(STAMP)
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==10
    assert store.db.execute("SELECT count(*) FROM feed_pages WHERE scope='actions'").fetchone()[0]==1
    assert store.db.execute("SELECT cursor FROM feed_jobs WHERE scope='actions'").fetchone()[0]=='10'
    monkeypatch.setattr(ing.progress,'update',original)
    ing.run(STAMP)
    assert store.db.execute('SELECT count(*) FROM action_sources').fetchone()[0]==20


def test_commit_failure_rolls_back_before_any_failure_status_write(store):
    real=store.db
    class FailingCommit:
        def __getattr__(self,name): return getattr(real,name)
        def commit(self): raise RuntimeError('injected commit failure')
    store.db=FailingCommit()
    try:
        with pytest.raises(RuntimeError,match='commit failure'):
            with store.transaction():
                store.record('actions','must-rollback',{'id':'must-rollback'},STAMP)
                store.advance('actions',STAMP)
        assert not real.in_transaction
        assert store.checkpoint('actions') is None
        assert not real.execute("SELECT 1 FROM records WHERE record_id='must-rollback'").fetchone()
    finally: store.db=real


def test_status_on_legacy_database_does_not_migrate(cfg,store,monkeypatch):
    with store.transaction(): store.db.execute('PRAGMA user_version=2')
    monkeypatch.setattr(Store,'migrate',lambda *args:pytest.fail('status must not migrate'))
    assert status(cfg.root)['state']=='upgrade_needed'
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2


def test_upgrade_refuses_wrong_empty_root(cfg,capsys):
    from stox.cli import main
    assert main(['--root',str(cfg.root),'upgrade'])==1
    assert not (cfg.root/'state.sqlite').exists()
    assert 'refuses to initialize' in capsys.readouterr().err


def test_keyboard_interrupt_records_interrupted_run(cfg,monkeypatch):
    import stox.engine as engine
    class Interrupted:
        def run(self,*args): raise KeyboardInterrupt()
    monkeypatch.setattr(engine,'Ingestor',lambda *a,**kw:Interrupted())
    with pytest.raises(KeyboardInterrupt): engine.run(cfg,timestamp=STAMP)
    db=Store(cfg.root)
    try:
        assert db.db.execute('SELECT status FROM runs').fetchone()[0]=='interrupted'
        assert not status(cfg.root)['writer_active']
    finally: db.close()


def test_conflicting_same_asset_metadata_is_isolated(store,cfg):
    master=SecurityMaster(store)
    row=asset('AAPL')
    master.refresh([asset('QQQ',name='Invesco QQQ Trust, Series 1'),row,dict(row,exchange='NASDAQ')],STAMP)
    assert master.resolve('QQQ').ticker=='QQQ'
    with pytest.raises(ValueError): master.resolve('AAPL')
    master.check_failure_budget(cfg)  # one ambiguous identity does not discard the other asset
