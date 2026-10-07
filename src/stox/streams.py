"""Atomic page receipts and frozen, bounded date-window provider requests."""
from datetime import date, timedelta
import json
import re
from .storage import digest, now_iso
from .providers.http import ProviderError

ANNOTATIONS = {'security_references','resolved_tickers','identifier_resolution'}

def action_raw(row):
    return {k:v for k,v in row.items() if k not in ANNOTATIONS}


def reuse_legacy_actions(store, master, progress, batch_size=1000):
    """Index existing payloads without changing their history or guessing range completeness."""
    scope='migration:action_sources'
    if store.checkpoint(scope+':done'):
        return
    end=store.checkpoint(scope+':end')
    if end is None:
        end=store.db.execute('SELECT coalesce(max(rowid),0) FROM records').fetchone()[0]
        store.advance(scope+':end',end)
    position=int(store.checkpoint(scope) or 0)
    processed=0
    while position<int(end):
        # Rowid keyset scan is linear, including on the old schema. Never OFFSET a growing table.
        rows=store.db.execute('SELECT rowid,* FROM records WHERE rowid>? AND rowid<=? ORDER BY rowid LIMIT ?',
                              (position,int(end),batch_size)).fetchall()
        if not rows: break
        with store.transaction():
            for r in rows:
                if r['kind']!='actions': continue
                payload=json.loads(r['payload'])
                raw=action_raw(payload)
                revision=r['revision']
                if 'security_references' not in payload:
                    payload=master.annotate_action(raw)
                    revision=store.record('actions',r['record_id'],payload,r['available_at'])
                store.db.execute('INSERT OR IGNORE INTO action_sources VALUES(?,?,?,?)',
                    (r['record_id'],digest(raw),revision,r['available_at']))
                processed+=1
            position=rows[-1]['rowid']
            store.advance(scope,position)
            progress.update(processed=processed, scanned_rows=position, legacy_end_rowid=int(end))
    with store.transaction():
        store.advance(scope+':done','1')
        store.advance('action_identifier_schema','3')


def window_end(start,target):
    # Inclusive dates; the next window starts the following day.
    return min(date.fromisoformat(start)+timedelta(days=30),date.fromisoformat(target[:10])).isoformat()


def ingest_feed(store, api, feed, start, target, consume, progress):
    """Returns the fully completed snapshot; unfinished jobs retain original query boundaries.

    A page's rows, typed IDs, raw-payload receipt, page receipt and cursor are one FULL
    synchronous WAL transaction. Provider I/O happens before BEGIN. An expired cursor
    replays only its current <=31-day window, never the completed history.
    """
    job=store.db.execute('SELECT * FROM feed_jobs WHERE scope=?',(feed,)).fetchone()
    if not job or job['status']!='running':
        job_key=digest([feed,start,target])
        with store.transaction():
            store.db.execute('INSERT OR REPLACE INTO feed_jobs VALUES(?,?,?,?,?,?,?,?,0,0,0,0,0,?)',
                (feed,job_key,start,target,start,window_end(start,target),None,'running',now_iso()))
        job=store.db.execute('SELECT * FROM feed_jobs WHERE scope=?',(feed,)).fetchone()
    progress.update(processed=job['processed'],resume_processed=job['processed'],pages=job['pages'],inserted=job['inserted'],skipped=job['skipped'])
    while job['status']=='running':
        try:
            rows,next_token=api.event_page(feed,job['window_start'],job['window_end'],job['cursor'],job['target'])
        except ProviderError as exc:
            if (job['cursor'] and exc.status_code in (400,410,422)
                    and re.search(r'(page.?token|cursor).*(invalid|expired)|(invalid|expired).*(page.?token|cursor)',str(exc),re.I)
                    and job['resets']<2):
                with store.transaction():
                    store.db.execute('UPDATE feed_jobs SET cursor=NULL,resets=resets+1,updated_at=? WHERE scope=?',(now_iso(),feed))
                    store.db.execute('DELETE FROM feed_pages WHERE scope=? AND job_key=? AND window_start=?',
                                     (feed,job['job_key'],job['window_start']))
                job=store.db.execute('SELECT * FROM feed_jobs WHERE scope=?',(feed,)).fetchone()
                continue
            raise
        token_hash=digest(job['cursor'])
        next_hash=digest(next_token) if next_token else None
        if next_token and (next_token==job['cursor'] or store.db.execute(
            'SELECT 1 FROM feed_pages WHERE scope=? AND job_key=? AND window_start=? AND cursor_hash=?',
            (feed,job['job_key'],job['window_start'],next_hash)).fetchone()):
            raise ProviderError(f'{feed}: repeated pagination token; durable cursor retained')
        with store.transaction():
            inserted,skipped=consume(rows)
            store.db.execute('INSERT OR REPLACE INTO feed_pages VALUES(?,?,?,?,?,?,?)',
                (feed,job['job_key'],job['window_start'],token_hash,next_hash,len(rows),now_iso()))
            new_start,new_end=job['window_start'],job['window_end']
            done=not next_token and new_end>=job['target'][:10]
            if not next_token and not done:
                new_start=(date.fromisoformat(new_end)+timedelta(days=1)).isoformat()
                new_end=window_end(new_start,job['target'])
            store.db.execute('UPDATE feed_jobs SET window_start=?,window_end=?,cursor=?,status=?,pages=pages+1,processed=processed+?,inserted=inserted+?,skipped=skipped+?,updated_at=? WHERE scope=?',
                (new_start,new_end,next_token,'complete' if done else 'running',len(rows),inserted,skipped,now_iso(),feed))
            if done:
                store.advance(feed,job['target'])
                store.health(feed,'PASS',('Corporate-action' if feed=='actions' else 'News')+' pagination completed')
            progress.update(processed=job['processed']+len(rows),pages=job['pages']+1,
                            inserted=job['inserted']+inserted,skipped=job['skipped']+skipped,
                            window_start=new_start,window_end=new_end,snapshot=job['target'])
        job=store.db.execute('SELECT * FROM feed_jobs WHERE scope=?',(feed,)).fetchone()
    return job['target']
