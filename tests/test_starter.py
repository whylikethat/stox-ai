"""Fast-start policy, provider request contracts, and actual four-horizon training."""
from pathlib import Path
import json
import pandas as pd
import pytest
from stox.config import Config
from stox.ingestion import Ingestor, action_scope
from stox.security import SecurityMaster, MarketDataSymbol
from stox.providers.alpaca import Alpaca
from stox.storage import Store
from stox.features import enrich, FAMILIES
from test_bootstrap_resume import Paged, STAMP
from test_security_master import asset
from test_providers import FakeHTTP

STARTER=Path(__file__).parents[1]/'config.starter.toml'

class Filtered(Paged):
    def event_page(self,feed,start,end,cursor=None,snapshot=None,symbols=None):
        self.filters=getattr(self,'filters',[])+[(feed,tuple(r.ticker for r in symbols or []))]
        return super().event_page(feed,start,end,cursor,snapshot)

@pytest.mark.parametrize('days',[60,90])
def test_news_independent_history_and_incremental(cfg,store,calendar,days):
    cfg.history_start='2023-01-01';cfg.news_lookback_days=days
    api=Paged(calendar,0);ing=Ingestor(cfg,store,calendar,api)
    # A pre-repair unbounded in-flight job must not dictate this policy's window.
    ing.events('news',SecurityMaster(store),STAMP,'2025-01-07')
    floor=(pd.Timestamp(STAMP)-pd.Timedelta(days=days)).date().isoformat()
    assert api.page_calls[0][1]==floor
    assert all(c[1]>=floor for c in api.page_calls)
    api.page_calls.clear()
    ing.events('news',SecurityMaster(store),STAMP,'2025-01-07')
    assert not api.page_calls
    ing.events('news',SecurityMaster(store),'2025-01-08T22:00:00+00:00','2025-01-08')
    assert api.page_calls[0][1]=='2024-12-31'


def disable(cfg):
    cfg.enable_news=cfg.enable_sec=cfg.enable_fred=cfg.enable_alpha_vantage=False


def test_disabled_sources_zero_calls_and_scoped_actions(cfg,store,calendar,monkeypatch):
    import stox.ingestion as module
    disable(cfg);cfg.history_start='2025-01-01';cfg.symbols=('SPY','QQQ','AAPL')
    cfg.secrets={'ALPHAVANTAGE_API_KEY':'present-but-disabled'}
    def forbidden(*a,**kw): pytest.fail('Disabled provider constructed')
    for name in ('SEC','FRED','AlphaVantage'): monkeypatch.setattr(module,name,forbidden)
    api=Filtered(calendar,20,10);ing=Ingestor(cfg,store,calendar,api)
    ing.run(STAMP)
    assert all(c[0]=='actions' for c in api.page_calls)
    assert all(set(f[1])==set(cfg.symbols) for f in api.filters)
    scope=action_scope(cfg,cfg.symbols)
    assert store.checkpoint(scope)==STAMP and store.checkpoint('actions') is None
    assert {r['provider'] for r in store.db.execute("SELECT * FROM health WHERE status='DISABLED'")}=={'news','sec','fred','alpha'}
    count=len(store.records('actions'));api.page_calls.clear()
    ing.run(STAMP)
    assert not api.page_calls and len(store.records('actions'))==count
    cfg.symbols+=('MSFT',)
    ing.run(STAMP)
    assert api.page_calls and len(store.records('actions'))==count
    assert store.checkpoint(action_scope(cfg,cfg.symbols))==STAMP
    # Full-universe mode remains a separate, unfiltered job.
    cfg.symbols=();api.filters.clear();ing.run(STAMP)
    assert all(not f[1] for f in api.filters)
    assert store.checkpoint('actions')==STAMP


def test_action_filter_namespace_and_provider_contract():
    http=FakeHTTP([{'corporate_actions':{},'next_page_token':None}])
    api=Alpaca({'ALPACA_API_KEY':'fixture','ALPACA_API_SECRET':'fixture'},http)
    api.event_page('actions','2023-01-01','2023-01-31',symbols=[MarketDataSymbol('QQQ','provider-id','alpaca_assets'),MarketDataSymbol('SPY','other','alpaca_assets')])
    assert http.calls[0][1]['params']['symbols']=='QQQ,SPY'
    assert 'cusips' not in http.calls[0][1]['params']
    with pytest.raises(ValueError): api.event_page('actions','2023-01-01','2023-01-31',symbols=['09175M861'])


def test_cached_enrichment_is_not_used_when_disabled(cfg,store):
    disable(cfg)
    store.record('news','n',{'id':'n','symbols':['SPY'],'created_at':'2024-01-01T00:00:00Z','headline':'news'},STAMP)
    store.record('filings','f',{'symbol':'SPY','available_at':STAMP},STAMP)
    frame=pd.DataFrame({'symbol':['SPY'],'issue_at':[STAMP]})
    result=enrich(frame,store,cfg)
    assert result[sum([v for k,v in FAMILIES.items() if k!='price'],[])].isna().all().all()
    from stox.reporting import evidence
    assert not evidence(store,'SPY',STAMP,cfg)['news']
    assert not evidence(store,'SPY',STAMP,cfg)['filings']


def test_news_does_not_invent_zeros_before_available_history(cfg,store):
    store.record('news','n',{'id':'n','symbols':['SPY'],'created_at':'2025-01-01T00:00:00Z'},STAMP)
    frame=pd.DataFrame({'symbol':['SPY','SPY'],'issue_at':['2023-01-01T00:00:00Z','2025-02-02T00:00:00Z']})
    result=enrich(frame,store,cfg)
    assert pd.isna(result.news_count.iloc[0]) and result.news_count.iloc[1]==0


def test_config_defaults_and_starter(tmp_path):
    starter=Config.load(str(STARTER),str(tmp_path/'state'))
    assert 75<=len(starter.symbols)<=150 and len(set(starter.symbols))==len(starter.symbols)
    assert {'SPY','QQQ','XLF','XLV','XLE','XLP','XLU','XLRE'}<=set(starter.symbols)
    assert starter.history_start=='2023-01-01' and not starter.enable_news
    full=Config.load(str(STARTER.with_name('config.example.toml')),str(tmp_path/'full'))
    assert not full.symbols and all((full.enable_news,full.enable_sec,full.enable_fred,full.enable_alpha_vantage))
    for text in ('news_lookback_days = 0','enable_sec = "false"'):
        p=tmp_path/'invalid.toml';p.write_text('[stox]\n'+text)
        with pytest.raises(ValueError): Config.load(str(p))


def test_starter_real_training_four_horizons_and_incremental(tmp_path,monkeypatch):
    from stox.demo import seed
    import stox.ingestion as ingestion
    import stox.models as models
    from stox.engine import run
    cfg=Config.load(str(STARTER),str(tmp_path/'starter'))
    stamp=seed(cfg,end='2026-10-09',start=cfg.history_start)
    db=Store(cfg.root);assets=db.records('assets');db.close()
    class Fixture:
        calls=[]
        def assets(self): return assets
        def bars(self,*args): pytest.fail('Completed price histories should be reused')
        def event_page(self,feed,start,end,cursor=None,snapshot=None,symbols=None):
            assert feed=='actions'
            self.calls.append((feed,start,end))
            return [],None
    api=Fixture();monkeypatch.setattr(ingestion,'Alpaca',lambda *a:api)
    for name in ('SEC','FRED','AlphaVantage'):
        monkeypatch.setattr(ingestion,name,lambda *a,**kw:pytest.fail('disabled source called'))
    report,path=run(cfg,timestamp=stamp,synthetic=True)
    assert set(report['backtests'])=={'20','30','60','90'}
    assert len(report['research_candidates'])==32
    assert all(r['feature_families']=='price' for r in report['research_candidates'])
    assert all((path/f).exists() for f in ('report.json','report.md','report.html','ai_review.md'))
    assert 'intentionally disabled' in (path/'report.md').read_text()
    assert not report['metadata']['enrichment_profile']['enable_sec']
    db=Store(cfg.root)
    counts=tuple(db.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('models','forecasts','records'))
    db.close();api.calls.clear()
    monkeypatch.setattr(models,'train_horizon',lambda *a:pytest.fail('Completed models should be reused'))
    second,_=run(cfg,timestamp=stamp,synthetic=True)
    assert not api.calls
    assert second['metadata']['model_ids']==report['metadata']['model_ids']
    assert second['new_forecast_count']==0
    assert second['research_forecast_ids']==report['research_forecast_ids']
    db=Store(cfg.root)
    assert counts==tuple(db.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('models','forecasts','records'))
    db.close()


def test_restricted_action_interruption_reuses_cursor(cfg,store,calendar):
    from stox.providers.http import ProviderError
    disable(cfg);cfg.history_start='2025-01-01';cfg.symbols=('SPY','QQQ')
    api=Filtered(calendar,20,10);api.fail_cursor='10';api.fail_once=True
    ing=Ingestor(cfg,store,calendar,api)
    with pytest.raises(ProviderError): ing.run(STAMP)
    scope=action_scope(cfg,cfg.symbols)
    assert store.checkpoint(scope) is None
    assert store.db.execute('SELECT cursor FROM feed_jobs WHERE scope=?',(scope,)).fetchone()[0]=='10'
    api.page_calls.clear();ing.run(STAMP)
    assert api.page_calls[0][3]=='10'
    assert len(store.records('actions'))==20


def test_live_doctor_respects_disabled_sources(cfg,monkeypatch):
    import stox.doctor as module
    disable(cfg)
    class Core:
        def __init__(self,*a): pass
        def assets(self): return []
        def actions(self,*a): yield []
        def news(self,*a): pytest.fail('Disabled news in live doctor')
    monkeypatch.setattr(module,'Alpaca',Core)
    monkeypatch.setattr(module,'sip_preflight',lambda *a:'fixture bar')
    for name in ('SEC','FRED','AlphaVantage'):
        monkeypatch.setattr(module,name,lambda *a,**kw:pytest.fail('Disabled optional doctor provider'))
    checks=module.doctor(cfg,live=True,vintages=True)
    assert sum(c['status']=='DISABLED' for c in checks)==4
    assert not any(c['status']=='FAIL' for c in checks)


def test_history_expansion_is_durable_and_does_not_repeat(cfg,store,calendar):
    disable(cfg);cfg.history_start='2025-01-01'
    api=Filtered(calendar,0);ing=Ingestor(cfg,store,calendar,api)
    ing.run(STAMP)
    cfg.history_start='2024-11-01'
    original=api.bars;calls=[]
    def bars(refs,start,end):
        calls.append((refs[0].ticker,start,end))
        yield from original(refs,start,end)
    api.bars=bars
    ing.run(STAMP)
    assert any(c[1]=='2024-11-01' for c in calls)
    assert store.checkpoint('bars:SPY:history_start')=='2024-11-01'
    calls.clear();api.page_calls.clear();ing.run(STAMP)
    assert not calls and not api.page_calls


def test_incompatible_champion_is_not_reused(cfg,store,monkeypatch):
    from types import SimpleNamespace
    import stox.models as module
    from stox.storage import encode
    disable(cfg);cfg.horizons=(30,)
    store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',('old',30,STAMP,'champion','models/old.joblib','{}'))
    store.db.commit()
    old=SimpleNamespace(columns=['momentum_20','news_count'],metadata={'holdout_end':'2024-01-01'})
    monkeypatch.setattr(module.joblib,'load',lambda *a:old)
    attempted=[]
    def train(*a):
        attempted.append(True)
        raise ValueError('No fixture fit; cannot fall back to disabled-family model')
    monkeypatch.setattr(module,'train_horizon',train)
    labels=pd.DataFrame({'horizon':[30],'label_end':['2025-01-01'],'momentum_20':[.1],'news_count':[float('nan')]})
    assert module.registry_train(labels,cfg,store,stamp=STAMP)=={}
    assert attempted


def test_fred_failure_allows_existing_price_model(cfg,store,calendar,monkeypatch):
    import stox.ingestion as ingestion
    import stox.models as models
    from types import SimpleNamespace
    disable(cfg);cfg.enable_fred=True;cfg.horizons=(30,)
    def fail(*a): raise RuntimeError('FRED unavailable')
    monkeypatch.setattr(ingestion,'FRED',fail)
    warnings=[];Ingestor(cfg,store,calendar,Paged(calendar,0)).optional([],STAMP,warnings)
    assert any('FRED unavailable' in w for w in warnings)
    store.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',('old',30,STAMP,'champion','models/old.joblib','{}'));store.db.commit()
    old=SimpleNamespace(columns=['momentum_20'],metadata={'holdout_end':'2024-01-01'})
    monkeypatch.setattr(models.joblib,'load',lambda *a:old)
    monkeypatch.setattr(models,'train_horizon',lambda *a:pytest.fail('Compatible price champion should be reused'))
    labels=pd.DataFrame({'horizon':[30],'label_end':['2025-01-01'],'momentum_20':[.1]})
    assert models.registry_train(labels,cfg,store,stamp=STAMP)[30] is old


def test_disabled_sources_do_not_disqualify_valid_price_forecast(cfg):
    """Manufactured validated fixture tests policy only, not investment accuracy."""
    import numpy as np
    from types import SimpleNamespace
    from stox.ranking import forecast_rows
    disable(cfg)
    bucket={'bucket':8,'n':1000,'blocks':20,'interval':[.7,.9],'probability':.8,'win_rate':.8}
    model=SimpleNamespace(committee=None,algorithm='fixture',model_id='fixture',
        metadata={'family':'price','validated':True,'threshold':.7,'evaluation':{'buckets':[bucket],'interval_80_coverage':.8}},
        predict=lambda f:(np.array([[.99,.98,.95,.8,.75,.6]]),np.array([.04]),np.array([[-.02,.03,.1]])))
    features=pd.DataFrame([{'symbol':'SPY','session':'2025-01-07','close':100,'dollar_volume':1e9,'history_count':900,'missing_recent':0,'volatility':.1,'drawdown':-.02}])
    assets=[{'symbol':'SPY','security_type':'etf','queryable':True,'tradable':True,'status':'active'}]
    rows=forecast_rows(features,assets,{30:model},cfg,'2025-01-07')
    assert rows[0]['qualified'] and not rows[0]['exclusions']


def test_price_prefix_interrupt_reuses_completed_windows(cfg,store,calendar):
    from stox.providers.http import ProviderError
    disable(cfg);cfg.history_start='2025-01-01'
    api=Filtered(calendar,0);ing=Ingestor(cfg,store,calendar,api);ing.run(STAMP)
    cfg.history_start='2024-11-01';original=api.bars;calls=[];fail=[True]
    def bars(refs,start,end):
        calls.append(start)
        if start=='2024-12-02' and fail[0]:
            fail[0]=False
            raise ProviderError('interrupted prefix')
        yield from original(refs,start,end)
    api.bars=bars
    with pytest.raises(ProviderError): ing.run(STAMP)
    assert store.checkpoint('bars:AAPL:prefix:2024-11-01')=='2024-12-02'
    calls.clear();ing.run(STAMP)
    assert calls[0]=='2024-12-02'

