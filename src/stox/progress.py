"""Durable stage status, with bounded terminal output and no invented ETA."""
from contextlib import contextmanager
import time
from .storage import encode, now_iso

class Progress:
    def __init__(self, store, run_id):
        self.store, self.run_id = store, run_id
        self.name = None
        self.started = self.last_print = 0
        self.counters = {}

    @contextmanager
    def stage(self, name, total=None):
        self.name, self.started, self.last_print = name, time.monotonic(), 0
        self.counters = {'processed':0, 'pages':0, 'inserted':0, 'skipped':0, 'errors':0, 'total':total}
        stamp = now_iso()
        with self.store.transaction():
            self.store.db.execute('INSERT OR REPLACE INTO stages VALUES(?,?,?,?,?,?,?)',
                (self.run_id,name,'running',stamp,stamp,None,encode(self.counters)))
        self.update(force=True)
        try:
            yield self
        except BaseException as exc:
            self.counters['error']=str(exc) or type(exc).__name__
            self.finish('interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed')
            raise
        else:
            self.finish('degraded' if self.counters.get('errors') else 'complete')

    def update(self, force=False, **counts):
        self.counters.update(counts)
        elapsed = time.monotonic()-self.started
        self.counters['elapsed_seconds'] = round(elapsed,2)
        # Overall totals are often unknown; no record-based ETA for provider pagination.
        self.counters['rate_per_second'] = round(max(0,self.counters.get('processed',0)-self.counters.get('resume_processed',0))/max(elapsed,0.001),2)
        with self.store.transaction():
            self.store.db.execute('UPDATE stages SET progress=?,updated_at=? WHERE run_id=? AND name=?',
                (encode(self.counters),now_iso(),self.run_id,self.name))
        if force or time.monotonic()-self.last_print>=15:
            self.last_print=time.monotonic()
            print(f'[{self.name}] '+', '.join(f'{k}={v}' for k,v in self.counters.items() if v is not None),flush=True)

    def finish(self, status):
        self.update(force=True)
        with self.store.transaction():
            self.store.db.execute('UPDATE stages SET status=?,updated_at=?,finished_at=? WHERE run_id=? AND name=?',
                (status,now_iso(),now_iso(),self.run_id,self.name))
        print(f'[{self.name}] {status}',flush=True)
