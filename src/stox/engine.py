from __future__ import annotations
import json
import logging
import subprocess
import uuid
from logging.handlers import RotatingFileHandler
import pandas as pd
from threadpoolctl import threadpool_limits
from . import __version__
from .calendar import MarketCalendar,utc
from .storage import Store,encode,now_iso,digest
from .security import SecurityMaster
from .ingestion import Ingestor
from .features import build_features,make_labels
from .models import registry_train
from .ranking import forecast_rows,leaderboards
from .predictions import settle,issue,performance
from .holdings import review
from .reporting import evidence,write_reports


def git_commit():
    try:
        from pathlib import Path
        return subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[2],stderr=subprocess.DEVNULL,text=True).strip()
    except (OSError,subprocess.CalledProcessError):
        return 'unknown (installed distribution)'

def run(cfg,offline=False,force_train=False,timestamp=None,synthetic=False):
    cfg.initialize()
    store=Store(cfg.root)
    cal=MarketCalendar()
    started=utc(timestamp).isoformat()
    rid=started.replace(':','').replace('+','_')+'-'+uuid.uuid4().hex[:8]
    handler=RotatingFileHandler(cfg.root/'logs'/'stox.log',maxBytes=2_000_000,backupCount=3)
    logger=logging.getLogger('stox')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        with store.lock():
            store.storage_check(cfg.soft_storage_gb,cfg.hard_storage_gb)
            with store.db:
                store.db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(rid,started,None,'running','{}'))
            warnings=[]
            if not offline:
                session,warnings=Ingestor(cfg,store,cal).run(started)
            else:
                session=cal.completed(started)
                warnings.append('Offline run: no providers contacted; cached data only')
            if synthetic:
                warnings.append('SYNTHETIC DATA: model results are a software demonstration, not investment evidence')
            master=SecurityMaster(store)
            master.ensure(started)
            master.resolve_holdings()
            master.check_failure_budget(cfg)
            assets=master.assets()
            symbols=[r.ticker for r in master.requests(cfg)]
            for benchmark in ('SPY','QQQ'):
                if benchmark not in symbols:
                    raise RuntimeError(f'FORECASTING BLOCKED: {benchmark} is not an authoritative queryable asset')
            for benchmark in ('SPY','QQQ'):
                b=store.bars(benchmark)
                if b.empty or b.session.max()!=session:
                    raise RuntimeError(f'FORECASTING BLOCKED: {benchmark} lacks latest completed session {session}')
            expected_symbols={a['symbol'] for a in assets if a.get('status')=='active' and a.get('security_type') in ('common','etf') and a['symbol'] in symbols}
            summary={r[0]:r[2] for r in store.warehouse_summary()}
            covered=sum(summary.get(s)==session for s in expected_symbols)
            if expected_symbols and covered/len(expected_symbols)<cfg.min_core_coverage:
                raise RuntimeError(f'FORECASTING BLOCKED: latest-session coverage {covered}/{len(expected_symbols)} is below the configured minimum')
            if not store.checkpoint('actions'):
                raise RuntimeError('FORECASTING BLOCKED: corporate-action feed has no successful checkpoint')
            if pd.Timestamp(store.checkpoint('actions')) < cal.close(session):
                raise RuntimeError('FORECASTING BLOCKED: corporate-action checkpoint is stale')
            logger.info(encode({'run':rid,'stage':'features'}))
            features,errors=build_features(store,symbols,cal,cal.close(session).isoformat(),cfg.max_training_rows)
            warnings.extend(f'{s}: {reason}' for s,reason in errors.items())
            labels=make_labels(features,store,cal,cfg.horizons,cfg.friction_bps)
            if labels.empty:
                raise RuntimeError('FORECASTING BLOCKED: insufficient mature labels; bootstrap more history')
            labels=labels[pd.to_datetime(labels.label_available_at,utc=True)<=utc(started)]
            settlement=settle(store,cal,started,cfg.friction_bps)
            warnings.extend(settlement['warnings'])
            logger.info(encode({'run':rid,'stage':'models','label_rows':len(labels)}))
            models=registry_train(labels,cfg,store,force_train,started)
            if set(models)!=set(cfg.horizons):
                raise RuntimeError('FORECASTING BLOCKED: all active horizons need trained models; inspect stox status')
            # Fresh event cutoff is the run snapshot. Preserve price cutoff independently.
            from .features import enrich
            current=features.sort_values('session').groupby('symbol').tail(1).copy()
            current['issue_at']=started
            current=enrich(current,store)
            rows=forecast_rows(current,assets,models,cfg,session)
            health={r['provider']:r['status'] for r in store.db.execute('SELECT * FROM health')}
            for row in rows:
                for family,provider in (('news','news'),('fundamentals','sec'),('macro','fred')):
                    if family in row['feature_families'] and health.get(provider)!='PASS' and not synthetic:
                        row['qualified']=False
                        row['exclusions'].append('Selected '+family+' source is degraded')
                if row['exclusions'] and row['quality_label']=='High Confidence / Lower Return':
                    row['quality_label']='Research only / below preferred return'
            primary,across=leaderboards(rows)
            for row in rows:
                row['primary_rank']=next((p['rank'] for p in primary if p['symbol']==row['symbol'] and row['horizon']==30),None)
                row['across_rank']=next((p['rank'] for p in across if p['symbol']==row['symbol'] and p['horizon']==row['horizon']),None)
            holdings=review(store,rows,rid)
            highlights={r['symbol'] for r in primary[:3]+across[:3]}|{h['symbol'] for h in holdings if h['status']!='HEALTHY'}
            for holding in holdings:
                holding['evidence']=evidence(store,holding['symbol'],started)
            details=[]
            with threadpool_limits(limits=cfg.threads):
                for symbol in sorted(highlights|{r['symbol'] for r in primary+across}):
                    forecasts=[r for r in rows if r['symbol']==symbol]
                    fr=current[current.symbol==symbol]
                    if not fr.empty and symbol in highlights:
                        for r in forecasts:
                            r['explanations']=models[r['horizon']].explain(fr.iloc[0].to_dict())
                    details.append({'symbol':symbol,'forecasts':forecasts,'evidence':evidence(store,symbol,started)})
            if any(not m.metadata['validated'] for m in models.values()):
                warnings.append('One or more research models have not passed qualification; unvalidated horizons cannot issue official recommendations')
            warnings.append('Historical universe reconstruction is approximate; historical asset metadata and revisions are incomplete before first local observation')
            cleanup_models(store)
            metadata={'version':__version__,'git_commit':git_commit(),'run_started':started,
                      'market_session':session,'market_cutoff':cal.close(session).isoformat(),'event_cutoff':started,
                      'news_checkpoint':store.checkpoint('news'),'sec_checkpoint':store.checkpoint('sec'),'macro_checkpoint':store.checkpoint('fred'),
                      'model_ids':{str(h):m.model_id for h,m in models.items()},'feature_version':'causal-v2',
                      'data_digest':digest([(s,store.checkpoint('bars:'+s)) for s in symbols]),'universe_digest':digest(assets),'universe_diagnostics':master.persist_diagnostics(cfg,session),
                      'friction_bps':cfg.friction_bps,'provider_health':[dict(r) for r in store.db.execute('SELECT * FROM health')],
                      'run_mode':'synthetic' if synthetic else 'offline' if offline else 'live',
                      'ranking_rule':'P(gain) first; expected return within comparable calibration resolution',
                      'limits':'No brokerage, trades, capital allocation, continuous monitoring, or tax advice'}
            # Issuance occurs after all computation, never backdated to data fetch start.
            issued=started if synthetic else now_iso()
            metadata['forecast_issued_at']=issued
            signature=digest([session,metadata['data_digest'],metadata['model_ids'],[(r['symbol'],r['horizon'],r['p_gain'],r['expected_return']) for r in rows]])
            duplicate=store.checkpoint('last_forecast_signature')==signature
            if duplicate:
                warnings.append('Same market/model forecast snapshot: no duplicate official forecasts issued')
                ids=[]
            elif not synthetic and offline:
                warnings.append('Offline research runs do not issue official prospective forecasts')
                ids=[]
            else:
                ids=issue(store,cal,rows,issued,metadata)
                store.advance('last_forecast_signature',signature)
            report={'run_id':rid,'synthetic':synthetic,'metadata':metadata,'warnings':warnings,'primary_30d':primary,
                    'across_horizons':across,'details':details,'research_candidates':rows,'holdings':holdings,
                    'prospective':performance(store),'backtests':{str(h):m.metadata['evaluation'] for h,m in models.items()},
                    'official_forecast_ids':ids,'settlement':settlement}
            path=write_reports(cfg.root,report)
            with store.db:
                store.db.execute('UPDATE runs SET finished_at=?,status=?,metadata=? WHERE id=?',(now_iso(),'success',encode(metadata),rid))
            logger.info(encode({'run':rid,'stage':'complete','official_forecasts':len(ids)}))
            return report,path
    except Exception as exc:
        with store.db:
            store.db.execute('UPDATE runs SET finished_at=?,status=?,metadata=? WHERE id=?',(now_iso(),'failed',encode({'error':str(exc)}),rid))
        logger.error(encode({'run':rid,'stage':'failed','error':str(exc)}))
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()
        store.close()


def cleanup_models(store):
    """Bound unreferenced artifacts; keep registry/audit metadata and every issued model."""
    referenced=set()
    for r in store.db.execute('SELECT payload FROM forecasts'):
        referenced.update(p['model_id'] for p in json.loads(r[0])['forecasts'] if p.get('model_id'))
    for h in [r[0] for r in store.db.execute('SELECT DISTINCT horizon FROM models')]:
        rows=store.db.execute('SELECT * FROM models WHERE horizon=? ORDER BY created_at DESC',(h,)).fetchall()
        keep={r['id'] for r in rows[:3]}|{r['id'] for r in rows if r['status']=='champion'}|referenced
        for r in rows:
            if r['id'] not in keep:
                (store.root/r['path']).unlink(missing_ok=True)
    for directory in ('cache','warehouse','models'):
        for p in (store.root/directory).rglob('*.tmp'):
            p.unlink(missing_ok=True)
