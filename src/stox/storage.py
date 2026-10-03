from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

SCHEMA = 2

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str, allow_nan=False)

def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()

class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'state.sqlite', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.migrate()

    def migrate(self):
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA:
            raise RuntimeError('Database was created by a newer STOX-AI version')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS security_master(asset_id TEXT PRIMARY KEY,market_symbol TEXT,provider_symbol TEXT,security_type TEXT,status TEXT,tradable INTEGER,queryable INTEGER,reason TEXT,metadata_hash TEXT,payload TEXT,updated_at TEXT,present INTEGER,intended_candidate INTEGER);
        CREATE INDEX IF NOT EXISTS security_symbol ON security_master(market_symbol);
        CREATE TABLE IF NOT EXISTS security_identifiers(entity_id TEXT,kind TEXT,value TEXT,source TEXT,role TEXT,effective_at TEXT,observed_at TEXT,PRIMARY KEY(entity_id,kind,value,source,role,effective_at));
        CREATE INDEX IF NOT EXISTS typed_identifier ON security_identifiers(kind,value);
        CREATE TABLE IF NOT EXISTS security_quarantine(asset_id TEXT PRIMARY KEY,metadata_hash TEXT,reason TEXT,quarantined_at TEXT,retry_after TEXT);
        CREATE TABLE IF NOT EXISTS price_history_owners(ticker TEXT PRIMARY KEY,asset_id TEXT,bound_at TEXT);
        CREATE TABLE IF NOT EXISTS checkpoints(scope TEXT PRIMARY KEY, value TEXT NOT NULL, succeeded_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS health(provider TEXT PRIMARY KEY, status TEXT, detail TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS records(kind TEXT, record_id TEXT, revision TEXT, available_at TEXT, ingested_at TEXT, payload TEXT, PRIMARY KEY(kind,record_id,revision));
        CREATE INDEX IF NOT EXISTS records_time ON records(kind,available_at);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, metadata TEXT);
        CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY, horizon INTEGER, created_at TEXT, status TEXT, path TEXT, metadata TEXT);
        CREATE TABLE IF NOT EXISTS forecasts(id TEXT PRIMARY KEY, issued_at TEXT, symbol TEXT, entry_session TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entries(forecast_id TEXT PRIMARY KEY REFERENCES forecasts(id), price REAL CHECK(price>0), recorded_at TEXT, source TEXT);
        CREATE TABLE IF NOT EXISTS outcomes(forecast_id TEXT REFERENCES forecasts(id), horizon INTEGER, session TEXT, net_return REAL, payload TEXT, PRIMARY KEY(forecast_id,horizon));
        CREATE TABLE IF NOT EXISTS holdings(id INTEGER PRIMARY KEY, symbol TEXT, purchased TEXT, price REAL CHECK(price>0), shares REAL CHECK(shares>0), forecast_id TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS holding_reviews(run_id TEXT, holding_id INTEGER, payload TEXT, PRIMARY KEY(run_id,holding_id));
        CREATE TABLE IF NOT EXISTS budgets(provider TEXT, day TEXT, calls INTEGER, PRIMARY KEY(provider,day));
        CREATE TABLE IF NOT EXISTS evaluations(model_id TEXT, kind TEXT, payload TEXT);
        CREATE TRIGGER IF NOT EXISTS immutable_forecast_update BEFORE UPDATE ON forecasts BEGIN SELECT RAISE(ABORT,'Immutable forecast'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_forecast_delete BEFORE DELETE ON forecasts BEGIN SELECT RAISE(ABORT,'Immutable forecast'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_entry_update BEFORE UPDATE ON entries BEGIN SELECT RAISE(ABORT,'Immutable entry'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_entry_delete BEFORE DELETE ON entries BEGIN SELECT RAISE(ABORT,'Immutable entry'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_outcome_update BEFORE UPDATE ON outcomes BEGIN SELECT RAISE(ABORT,'Immutable outcome'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_outcome_delete BEFORE DELETE ON outcomes BEGIN SELECT RAISE(ABORT,'Immutable outcome'); END;
        ''')
        holding_columns={r[1] for r in self.db.execute('PRAGMA table_info(holdings)')}
        for name,definition in [('security_id','TEXT'),('input_kind',"TEXT DEFAULT 'ticker'"),('resolution_status',"TEXT DEFAULT 'unverified'")]:
            if name not in holding_columns:
                self.db.execute(f'ALTER TABLE holdings ADD COLUMN {name} {definition}')
        self.db.execute(f'PRAGMA user_version={SCHEMA}')
        self.db.commit()

    @contextlib.contextmanager
    def lock(self):
        with (self.root / 'run.lock').open('a') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another STOX-AI process is writing this data directory') from None
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def checkpoint(self, scope):
        row = self.db.execute('SELECT value FROM checkpoints WHERE scope=?', (scope,)).fetchone()
        return row[0] if row else None

    def invalidate_checkpoint(self, scope, reason):
        previous = self.checkpoint(scope)
        if previous is not None:
            self.record('checkpoint_invalidations', scope, {'previous': previous, 'reason': reason}, now_iso())
            with self.db:
                self.db.execute('DELETE FROM checkpoints WHERE scope=?', (scope,))

    def advance(self, scope, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)', (scope,str(value),now_iso()))

    def health(self, provider, status, detail):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO health VALUES(?,?,?,?)', (provider,status,detail,now_iso()))

    def record(self, kind, record_id, payload, available_at, ingested_at=None):
        revision = digest(payload)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?)',
                            (kind,str(record_id),revision,str(available_at),ingested_at or now_iso(),encode(payload)))
        return revision

    def records(self, kind, cutoff=None):
        rows = self.db.execute('SELECT * FROM records WHERE kind=? ORDER BY available_at,ingested_at', (kind,))
        latest = {}
        for row in rows:
            if cutoff is None or pd.Timestamp(row['available_at']) <= pd.Timestamp(cutoff):
                latest[row['record_id']] = json.loads(row['payload'])
        return list(latest.values())

    def budget(self, provider, maximum, day=None):
        day = day or now_iso()[:10]
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO budgets VALUES(?,?,0)', (provider,day))
            changed = self.db.execute('UPDATE budgets SET calls=calls+1 WHERE provider=? AND day=? AND calls<?', (provider,day,maximum)).rowcount
        return bool(changed)

    def bars(self, symbol):
        path = self.root / 'warehouse' / 'bars' / f'{digest(symbol)[:20]}.parquet'
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def put_bars(self, symbol, frame):
        if frame.empty:
            return
        path = self.root / 'warehouse' / 'bars' / f'{digest(symbol)[:20]}.parquet'
        path.parent.mkdir(parents=True, exist_ok=True)
        old = self.bars(symbol)
        merged = pd.concat([old,frame], ignore_index=True).drop_duplicates('session',keep='last').sort_values('session')
        if not old.empty:
            prior = old.set_index('session')
            for row in frame.to_dict('records'):
                s = row['session']
                if s in prior.index and any(prior.loc[s,k] != row[k] for k in ('open','high','low','close','volume')):
                    self.record('bar_revision',f'{symbol}:{s}',prior.loc[s].to_dict(),prior.loc[s,'available_at'])
                    self.record('bar_correction',f'{symbol}:{s}',{'symbol':symbol,'session':s,'correction_available_at':row['ingested_at'],'prior':prior.loc[s].to_dict(),'revised':row},row['ingested_at'])
        tmp = path.with_suffix('.tmp')
        merged.to_parquet(tmp,index=False,compression='zstd')
        os.replace(tmp,path)

    def warehouse_summary(self):
        import duckdb
        path = self.root / 'warehouse' / 'bars'
        if not path.exists() or not list(path.glob('*.parquet')):
            return []
        with duckdb.connect() as db:
            return db.execute('SELECT symbol,count(*),max(session) FROM read_parquet(?) GROUP BY symbol ORDER BY symbol', [str(path/'*.parquet')]).fetchall()

    def storage_check(self, soft_gb, hard_gb):
        usage = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        free = shutil.disk_usage(self.root).free
        if usage >= hard_gb * 1e9 or free < 500_000_000:
            raise RuntimeError('Storage safety limit reached; free space before ingestion')
        return {'bytes':usage,'free_bytes':free,'soft_limit_exceeded':usage >= soft_gb * 1e9}

    def close(self):
        self.db.close()
