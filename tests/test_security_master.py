import copy
import json
import sqlite3
from pathlib import Path
import pandas as pd
import pytest
from stox.security import SecurityMaster,MarketDataSymbol,identifier_kind
from stox.providers.alpaca import Alpaca
from stox.providers.http import ProviderError
from stox.ingestion import Ingestor
from stox.storage import Store
from stox.holdings import add
from stox.universe import eligible

FIXTURE=json.loads((Path(__file__).parent/'fixtures/security_identifiers.json').read_text())
STAMP='2025-01-07T22:00:00Z'


def asset(ticker,**kwargs):
    return {'id':'asset-'+ticker,'symbol':ticker,'name':ticker+' Common Stock','class':'us_equity',
            'exchange':'NYSE','status':'active','tradable':True,**kwargs}


class FixtureAlpaca:
    def __init__(self,calendar,assets=None):
        self.calendar=calendar
        self.asset_rows=copy.deepcopy(assets if assets is not None else FIXTURE['assets'])
        self.calls=[]
        self.invalid=set()
        self.partial_once=set()
        self.empty=set()
        self.systemic=None

    def assets(self): return self.asset_rows

    def bars(self,references,start,end):
        assert all(isinstance(r,MarketDataSymbol) for r in references)
        ticker=references[0].ticker
        assert ticker!='09175M861'
        self.calls.append(ticker)
        if self.systemic: raise self.systemic
        if ticker in self.invalid:
            raise ProviderError('data.alpaca.markets: HTTP 400: invalid symbol: '+ticker,status_code=400)
        days=[s for s in self.calendar.sessions('2025-01-06',end[:10]) if s>=start[:10]]
        rows=[{'t':s+'T05:00:00Z','o':100,'h':102,'l':99,'c':101,'v':1000000} for s in days]
        if ticker in self.partial_once:
            self.partial_once.remove(ticker)
            yield {ticker:rows[:1]}
            raise ProviderError('data.alpaca.markets: HTTP 500: retry exhausted',status_code=500)
        yield {ticker:[] if ticker in self.empty else rows}

    def actions(self,*args): yield copy.deepcopy(FIXTURE['actions'])
    def news(self,*args): yield []


def run_ingestion(cfg,store,calendar,api):
    ingest=Ingestor(cfg,store,calendar,api)
    ingest.optional=lambda *args:None
    return ingest.run(STAMP)


def test_cusip_provenance_separate_from_ticker_and_no_promotion(store):
    master=SecurityMaster(store)
    master.refresh(FIXTURE['assets'],STAMP)
    assert identifier_kind('09175M861')=='cusip'
    assert master.resolve('GOOD').alpaca_asset_id=='asset-good'
    assert master.resolve_identifier('cusip','09175M861').ticker=='GOOD'
    with pytest.raises(ValueError): master.resolve('09175M861')
    before=store.db.execute('SELECT count(*) FROM security_master').fetchone()[0]
    event=master.annotate_action(FIXTURE['actions'][0])
    assert any(r['kind']=='cusip' and r['value']=='09175M861' for r in event['security_references'])
    assert any(r['value']=='037833100' and not r['queryable'] for r in event['security_references'])
    assert store.db.execute('SELECT count(*) FROM security_master').fetchone()[0]==before
    kinds={r[0] for r in store.db.execute("SELECT kind FROM security_identifiers WHERE entity_id='asset-good'")}
    assert {'ticker','alpaca_asset_id','cusip','isin','figi','sec_cik'}<=kinds


def test_active_flag_alone_does_not_authorize_private_share_class(store):
    master=SecurityMaster(store);master.refresh(FIXTURE['assets'],STAMP)
    with pytest.raises(ValueError): master.resolve('PRIVATE.B')
    with pytest.raises(ValueError): master.resolve('OLD')


@pytest.mark.parametrize('ticker',['BRK.B','BRK/B','ABCD-E','ABCDEFGHI','FOO12'])
def test_valid_varied_tickers_require_authoritative_metadata(store,ticker):
    master=SecurityMaster(store);master.refresh([asset(ticker)],STAMP)
    assert master.resolve(ticker).ticker==ticker
    with pytest.raises(ValueError): master.resolve('NOT-IN-ASSETS')


def test_api_boundary_rejects_untyped_identifiers_before_network():
    api=Alpaca({'ALPACA_API_KEY':'fixture','ALPACA_API_SECRET':'fixture'})
    for identifier in ('09175M861','US09175M8612','BBG000BLNNH6','asset-good','event-rename','SPY'):
        with pytest.raises(ValueError,match='MarketDataSymbol'):
            list(api.bars([identifier],'2025-01-01','2025-01-07'))
    with pytest.raises(ValueError): MarketDataSymbol('09175M861','asset-good')


def test_symbol_change_and_reverse_split_preserve_typed_history(store):
    master=SecurityMaster(store)
    master.refresh([asset('OLD',id='same-asset',cusip='09175M861')],STAMP)
    master.refresh([asset('NEW',id='same-asset',cusip='037833100')],'2025-01-08T22:00:00Z')
    assert master.resolve('NEW').alpaca_asset_id=='same-asset'
    with pytest.raises(ValueError): master.resolve('OLD')
    assert store.db.execute("SELECT 1 FROM security_identifiers WHERE entity_id='same-asset' AND kind='historical_ticker' AND value='OLD'").fetchone()
    event=master.annotate_action({**FIXTURE['actions'][2],'symbol':'NEW'})
    assert event['old_cusip']=='09175M861' and event['new_cusip']=='037833100'
    assert event['resolved_tickers']==['NEW']
    assert master.resolve_identifier('cusip','037833100').ticker=='NEW'


def test_active_identifier_conflict_is_quarantined_even_if_tradable(store,cfg):
    master=SecurityMaster(store)
    master.refresh([asset('GOOD'),asset('09175M861'),asset('asset-GOOD')],STAMP)
    assert master.resolve('GOOD')
    with pytest.raises(ValueError): master.resolve('09175M861')
    with pytest.raises(ValueError): master.resolve('asset-GOOD')
    with pytest.raises(RuntimeError,match='identifier-resolution failure: 2/3'):
        master.check_failure_budget(cfg)


def test_fixture_bootstrap_cusip_never_queried_and_idempotent_resume(cfg,store,calendar):
    cfg.min_history=2
    api=FixtureAlpaca(calendar)
    run_ingestion(cfg,store,calendar,api)
    assert set(api.calls)=={'GOOD','QQQ','SPY'}
    assert store.checkpoint('bars:09175M861') is None
    assert store.checkpoint('bars:GOOD')=='2025-01-07'
    assert len(store.bars('GOOD'))==2
    ids_before=store.db.execute('SELECT count(*) FROM security_identifiers').fetchone()[0]
    api.calls.clear()
    run_ingestion(cfg,store,calendar,api)
    assert api.calls==[]
    assert len(store.bars('GOOD'))==2
    assert store.db.execute('SELECT count(*) FROM security_identifiers').fetchone()[0]==ids_before
    assert store.db.execute("SELECT 1 FROM security_identifiers WHERE kind='cusip' AND value='09175M861'").fetchone()
    d=SecurityMaster(store).diagnostics(cfg,'2025-01-07')
    assert d['assets_discovered']==6 and d['queryable_tickers']==3
    assert d['final_eligible_universe']==3
    assert d['non_tradable_non_queryable']==3


def test_single_rejected_ticker_continues_and_metadata_repair_resumes(cfg,store,calendar):
    api=FixtureAlpaca(calendar,FIXTURE['assets']+[asset('BADTK')])
    api.invalid={'BADTK'}
    run_ingestion(cfg,store,calendar,api)
    assert set(api.calls)=={'BADTK','GOOD','QQQ','SPY'}
    assert store.checkpoint('bars:BADTK') is None
    assert store.checkpoint('bars:SPY')=='2025-01-07'
    assert store.db.execute('SELECT count(*) FROM security_quarantine').fetchone()[0]==1
    api.calls.clear();run_ingestion(cfg,store,calendar,api)
    assert api.calls==[]  # durable quarantine and valid per-symbol checkpoints
    api.invalid.clear()
    api.asset_rows[-1]['name']='Repaired Common Stock'
    run_ingestion(cfg,store,calendar,api)
    assert api.calls==['BADTK']
    assert store.checkpoint('bars:BADTK')=='2025-01-07'
    assert len(store.bars('GOOD'))==2


def test_partial_symbol_failure_resume_reuses_completed_work_no_duplicates(cfg,store,calendar):
    api=FixtureAlpaca(calendar)
    api.partial_once={'QQQ'}
    with pytest.raises(ProviderError,match='HTTP 500'):
        run_ingestion(cfg,store,calendar,api)
    assert store.checkpoint('bars:GOOD')=='2025-01-07'
    assert store.checkpoint('bars:QQQ') is None
    assert len(store.bars('QQQ'))==1
    assert store.checkpoint('actions') is None
    api.calls.clear();run_ingestion(cfg,store,calendar,api)
    assert api.calls==['QQQ','SPY']
    assert len(store.bars('QQQ'))==2
    assert not store.bars('QQQ').session.duplicated().any()
    assert store.checkpoint('actions')==STAMP.replace('Z','+00:00')


def test_excess_provider_symbol_failures_are_systemic(cfg,store,calendar):
    api=FixtureAlpaca(calendar,FIXTURE['assets']+[asset('BAD1'),asset('BAD2')])
    api.invalid={'BAD1','BAD2'}
    with pytest.raises(RuntimeError,match='2/5 intended active tradable'):
        run_ingestion(cfg,store,calendar,api)
    assert store.checkpoint('actions') is None
    assert store.records('universe_diagnostics')[0]['systemic_identifier_failures']==2


@pytest.mark.parametrize('code,message',[(401,'unauthorized'),(403,'forbidden'),(429,'rate limit'),(500,'server failure'),(400,'invalid start parameter')])
def test_systemic_provider_errors_remain_fatal(cfg,store,calendar,code,message):
    api=FixtureAlpaca(calendar)
    api.systemic=ProviderError(message,status_code=code)
    with pytest.raises(ProviderError,match=message): run_ingestion(cfg,store,calendar,api)
    assert store.db.execute('SELECT count(*) FROM security_quarantine').fetchone()[0]==0
    assert store.checkpoint('bars:GOOD') is None


def test_old_empty_checkpoint_is_not_trusted(cfg,store,calendar):
    store.advance('bars:GOOD','2025-01-07')
    api=FixtureAlpaca(calendar)
    api.empty={'GOOD'}
    run_ingestion(cfg,store,calendar,api)
    assert 'GOOD' in api.calls
    assert store.checkpoint('bars:GOOD') is None
    assert store.records('checkpoint_invalidations')[0]['previous']=='2025-01-07'
    assert SecurityMaster(store).diagnostics(cfg)['no_price_history']==1
    api.empty.clear();api.calls.clear()
    run_ingestion(cfg,store,calendar,api)
    assert api.calls==['GOOD']
    assert len(store.bars('GOOD'))==2


def test_config_and_legacy_holdings_cannot_bypass_master(cfg,store,calendar):
    cfg.symbols=('09175M861','GOOD','UNVERIFIED')
    with store.db:
        store.db.execute("INSERT INTO holdings(symbol,purchased,price) VALUES('09175M861','2025-01-01',100)")
    api=FixtureAlpaca(calendar)
    run_ingestion(cfg,store,calendar,api)
    assert set(api.calls)=={'GOOD','QQQ','SPY'}
    assert store.db.execute('SELECT resolution_status FROM holdings').fetchone()[0]=='unresolved/non-queryable'
    assert store.db.execute('SELECT input_kind FROM holdings').fetchone()[0]=='cusip'
    with pytest.raises(ValueError,match='CUSIP'): add(store,'09175M861','2025-01-01',100)


def test_schema_one_migration_retains_holdings_checkpoints_and_audit(tmp_path):
    root=tmp_path/'legacy';root.mkdir()
    db=sqlite3.connect(root/'state.sqlite')
    db.executescript("""
    PRAGMA user_version=1;
    CREATE TABLE holdings(id INTEGER PRIMARY KEY,symbol TEXT,purchased TEXT,price REAL,shares REAL,forecast_id TEXT,active INTEGER DEFAULT 1);
    INSERT INTO holdings VALUES(4,'GOOD','2025-01-01',100,2,NULL,1);
    CREATE TABLE checkpoints(scope TEXT PRIMARY KEY,value TEXT NOT NULL,succeeded_at TEXT NOT NULL);
    INSERT INTO checkpoints VALUES('bars:GOOD','2025-01-07','2025-01-07T22:00:00Z');
    """)
    db.close()
    store=Store(root)
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2
    assert store.checkpoint('bars:GOOD')=='2025-01-07'
    holding=dict(store.db.execute('SELECT * FROM holdings').fetchone())
    assert holding['id']==4 and holding['shares']==2
    assert holding['resolution_status']=='unverified'
    store.close()
    store=Store(root)
    assert store.db.execute('SELECT count(*) FROM holdings').fetchone()[0]==1
    store.close()


def test_ambiguous_ticker_and_reused_history_are_not_queryable(store):
    master=SecurityMaster(store)
    master.refresh([asset('GOOD')],STAMP)
    master.bind_history(master.resolve('GOOD'),STAMP)
    master.refresh([asset('GOOD',id='different-asset')],STAMP)
    with pytest.raises(ValueError): master.resolve('GOOD')
    assert 'different archived asset' in store.db.execute('SELECT reason FROM security_master WHERE present=1').fetchone()[0]
    master.refresh([asset('DUP',id='one'),asset('DUP',id='two')],STAMP)
    with pytest.raises(ValueError): master.resolve('DUP')
    assert master.db.execute('SELECT sum(queryable) FROM security_master').fetchone()[0]==0


def test_observed_price_and_liquidity_gate_final_universe(cfg,store,calendar):
    api=FixtureAlpaca(calendar)
    run_ingestion(cfg,store,calendar,api)
    cfg.min_history=2
    bars=store.bars('GOOD')
    bars.loc[:,['open','high','low','close']]=4.0
    store.put_bars('GOOD',bars)
    bars=store.bars('QQQ');bars.loc[:,'volume']=1.0
    store.put_bars('QQQ',bars)
    result=SecurityMaster(store).diagnostics(cfg,'2025-01-07')
    assert result['below_minimum_price']==1
    assert result['insufficient_liquidity_data']==1
    assert result['final_eligible_universe']==1
    assert 'price below minimum' in eligible(SecurityMaster(store).assets()[0],{'close':4},cfg)


def test_untrusted_identifier_sources_cannot_authorize_tickers(store):
    master=SecurityMaster(store)
    master.refresh([asset('GOOD')],STAMP)
    master.identifier('asset-GOOD','cusip','09175M861','sec','unverified')
    with pytest.raises(ValueError): master.resolve_identifier('cusip','09175M861')
    with pytest.raises(ValueError): master.resolve('09175M861')
