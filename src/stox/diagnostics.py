"""Fast read-only status; expensive forensic scans are explicitly opt-in."""
import fcntl
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from . import __version__


def reader(root):
    db=sqlite3.connect((Path(root)/'state.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def writer_active(root):
    path=Path(root)/'run.lock'
    if not path.exists(): return False
    with path.open('r') as file:
        try:
            fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(file,fcntl.LOCK_UN)
        return False


def sizes(root):
    paths={name:Path(root)/name for name in ('state.sqlite','state.sqlite-wal','state.sqlite-shm')}
    return {name:p.stat().st_size if p.exists() else 0 for name,p in paths.items()}


def status(root):
    result={'version':__version__,'root':str(root),'writer_active':writer_active(root),'database_files':sizes(root)}
    if not (Path(root)/'state.sqlite').exists():
        return {**result,'state':'not_initialized'}
    with closing(reader(root)) as db:
        schema=db.execute('PRAGMA user_version').fetchone()[0]
        result['schema']=schema
        if schema<3:
            return {**result,'state':'upgrade_needed','note':'Run stox upgrade after stopping bootstrap. Old-schema status avoids unindexed scans.'}
        def one(sql,args=()):
            row=db.execute(sql,args).fetchone()
            return dict(row) if row else None
        result['last_run']=one('SELECT * FROM runs ORDER BY started_at DESC LIMIT 1')
        result['last_success']=one("SELECT * FROM runs WHERE status='success' ORDER BY started_at DESC LIMIT 1")
        run=result['last_run']
        result['state']=run['status'] if run else 'not_started'
        if run and run['status']=='running' and not result['writer_active']:
            result['state']='interrupted (no writer lock; stored run was not finalized)'
        result['stages']=[dict(r) for r in db.execute('SELECT * FROM stages WHERE run_id=? ORDER BY started_at',(run['id'] if run else '',))]
        for stage in result['stages']: stage['progress']=json.loads(stage['progress'])
        latest=one('SELECT * FROM stages ORDER BY updated_at DESC LIMIT 1')
        if latest: latest['progress']=json.loads(latest['progress'])
        result['current_or_last_stage']=latest
        result['feeds']=[{k:r[k] for k in r.keys() if k!='cursor'} for r in db.execute('SELECT * FROM feed_jobs')]
        result['checkpoints']=[dict(r) for r in db.execute("SELECT * FROM checkpoints WHERE scope IN ('assets','security_master','actions','news','sec','fred','alpha','migration:action_sources:done','migration:action_sources')")]
        result['providers']=[dict(r) for r in db.execute("SELECT * FROM health WHERE provider IN ('alpaca-bars','actions','news','sec','fred','alpha')")]
        for key in ('universe','modeling_universe','validation','warehouse','database_diagnostics'):
            row=one('SELECT value,updated_at FROM runtime_meta WHERE key=?',(key,))
            result[key]={'value':json.loads(row['value']),'as_of':row['updated_at']} if row else None
        result['pages']={'page_count':db.execute('PRAGMA page_count').fetchone()[0],
                         'free_pages':db.execute('PRAGMA freelist_count').fetchone()[0],
                         'page_size':db.execute('PRAGMA page_size').fetchone()[0]}
    return result


def diagnose(root, deep=False, integrity=False):
    if (deep or integrity) and writer_active(root):
        raise ValueError('Stop bootstrap before deep/integrity scans; stox status remains safe while running')
    result=status(root)
    if not (Path(root)/'state.sqlite').exists(): return result
    with closing(reader(root)) as db:
        if integrity:
            result['integrity_check']=[r[0] for r in db.execute('PRAGMA integrity_check')]
        if not deep:
            result['note']='Use --deep for table counts and dbstat; those scans can take time. --integrity verifies database integrity.'
            return result
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        result['table_rows']={name:db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
        result['table_rows']=dict(sorted(result['table_rows'].items(),key=lambda x:x[1],reverse=True))
        if 'records' in names:
            result['records_by_kind']=[dict(r) for r in db.execute('SELECT kind,count(*) AS revisions,count(DISTINCT record_id) AS provider_ids FROM records GROUP BY kind')]
        if 'security_identifiers' in names:
            result['identifier_groups']=[dict(r) for r in db.execute('SELECT source,kind,count(*) AS rows FROM security_identifiers GROUP BY source,kind')]
            result['repeated_ticker_observations']=[dict(r) for r in db.execute("SELECT entity_id,value,count(*) AS observations FROM security_identifiers WHERE source='alpaca_assets' AND role='current_ticker' GROUP BY entity_id,value HAVING count(*)>1 ORDER BY observations DESC LIMIT 20")]
        if 'security_master' in names:
            result['failure_reasons']=[dict(r) for r in db.execute('SELECT reason,intended_candidate,count(*) AS n FROM security_master WHERE present=1 AND queryable=0 GROUP BY reason,intended_candidate')]
            result['benchmarks']=[dict(r) for r in db.execute("SELECT asset_id,market_symbol,provider_symbol,security_type,status,tradable,queryable,reason FROM security_master WHERE provider_symbol IN ('QQQ','SPY','AAPL','MSFT')")]
        try:
            result['storage_by_object']=[dict(r) for r in db.execute('SELECT name,sum(pgsize) AS bytes,sum(unused) AS unused_bytes FROM dbstat GROUP BY name ORDER BY bytes DESC')]
        except sqlite3.OperationalError:
            result['storage_by_object']='SQLite dbstat extension unavailable'
    return result


def compact(root):
    """Explicit stopped-writer maintenance only; no deletion of provenance/history."""
    import shutil
    from .storage import Store
    store=Store(root)
    try:
        with store.lock():
            integrity=[r[0] for r in store.db.execute('PRAGMA integrity_check')]
            if integrity!=['ok']:
                raise RuntimeError('Integrity check failed; compaction refused: '+str(integrity))
            before=sizes(root)
            needed=2*before['state.sqlite']+500_000_000
            if shutil.disk_usage(root).free < needed:
                raise RuntimeError(f'Compaction requires at least {needed} bytes free for temporary storage')
            result=store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if result[0]:
                raise RuntimeError('Other database readers are active; close them before compaction')
            store.db.execute('VACUUM')
            after_integrity=[r[0] for r in store.db.execute('PRAGMA integrity_check')]
            if after_integrity!=['ok']: raise RuntimeError('Post-compaction integrity check failed')
            store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            return {'integrity_check':after_integrity,'before':before,'after':sizes(root),'deleted_records':0}
    finally:
        store.close()

