# Bootstrap recovery, version 2.0.4 / schema 3

The batching/resume repair below was introduced in 2.0.3. Version 2.0.4 adds
[repository-local installation and temporary storage](LOCAL_STORAGE.md), without
another database schema migration. Follow that guide if setup failed with an I/O error.

Existing `.stox` is valuable runtime state. Keep it, including its SQLite database,
WAL/SHM sidecars, warehouse, checkpoints, models and reports. No reset, destructive
cleanup, automatic VACUUM, or mandatory multi-GB copy is part of this upgrade.

## What went wrong

The old `SecurityMaster.identifier()` committed for every field. A typical action
with an ID, ticker and CUSIP incurred three identifier transactions plus a separate
record transaction. SQLite's durable WAL commits can require storage syncs; on an
external drive tens/hundreds of thousands of these tiny commits can dominate elapsed
time. The interruption stack inside `with self.db` is consistent with this path.
The code proves the pathological transaction pattern; exact hardware/fsync timings
cannot be recovered from an untimed tail of strace.

Actions and news had only whole-feed checkpoints. Stopping before completion replayed
all pages from the previous feed checkpoint (or 2016 for a first run). Identical
payloads were protected by primary keys, but still incurred normalization, queries
and transaction overhead. Asset ticker identifiers used the invocation timestamp
as a new effective date on every refresh. This unnecessarily multiplied ticker
observations. Corporate-action typed lookup searched all matching event identifiers
before filtering to authoritative assets. Asset validation also loaded event-only
identifiers into a global conflict set; that could change future universe decisions.

`stox status` initialized/migrated the store, read every queryable security's entire
Parquet history to recompute universe diagnostics, and walked the data directory.
It was not a lightweight status operation. Ingestion repeated the directory walk
per symbol. These paths are now bounded or cached.

## Transaction, checkpoint and upgrade guarantees

- Schema 3 is one transactional, restart-safe, additive migration under the writer
  lock. Reopening schema 3 does no migration work. It adds feed jobs/page receipts,
  raw-action receipt keys, stage metadata, bar summaries and lookup/status indexes.
  FULL synchronous WAL durability remains enabled.
- Helper writes join the caller's transaction. Each event page (up to 1,000 action
  records or 50 news records) atomically commits identifiers, payload revisions,
  raw-action hashes, its page receipt, the next cursor and progress. No network call
  occurs inside that transaction. A failure rolls back the entire unfinished page.
- Requests have frozen parameters and at most 31-calendar-day windows. Completed
  windows are skipped on resume. Unfinished jobs retain their original target even
  if a new run starts days later, then perform bounded catch-up. A demonstrably
  expired page token replays only the current window, with at most two token resets;
  authentication, malformed requests and systemic failures remain visible errors.
- Raw provider fields determine action identity/version. Derived security annotations
  do not manufacture provider revisions. New raw versions preserve the previous
  payload and first-observation timestamps. A bounded resolution cache avoids
  repeating mappings for every occurrence. Corporate-action identifiers never
  authorize a bars ticker.
- `stox upgrade` builds raw-action receipts from existing durable rows in 1,000-row
  keyset batches, saving its own cursor. Already normalized rows and their original
  availability/ingestion timestamps are retained byte-for-byte. Older unannotated
  revisions receive separate annotations; original history is never deleted.
- **Legacy limitation:** old rows have no provider page token or proof of range
  completeness. Neither the newest action date nor the largest UUID establishes
  that a range is complete. The repair deliberately does not invent that proof (the provider windows use process dates, not simply ex-dates).
  An unfinished pre-2.0.3 feed needs one verification replay from its old feed
  checkpoint/history start. Matching stored payloads skip normalization, identifier
  insertion and payload insertion. New page receipts make subsequent interruptions
  genuinely resumable. This still contacts the provider but avoids repeating the
  pathological database work. Completed old feed checkpoints remain valid.
- Existing Parquet files and verified completed bar checkpoints are reused. New
  sessions fetch a three-day overlap from durable history, including a partial
  symbol whose final checkpoint was never saved. A newly eligible symbol such as
  QQQ may need its own first history download; the other completed histories remain.
- A first local metadata pass reads legacy bar files to populate compact summaries.
  Later diagnostics use file-stat-validated summaries, not repeated full histories.

## Other expensive stages and incremental operation

Assets refresh atomically. Its unchanged ticker observations no longer acquire a
new effective date every run; historical observations remain stored. SEC writes are
batched by 1,000 rows and checkpoints per company; downloaded response files survive
interruption of a company. Historical submissions are revalidated at least every
30 days; other responses are cached for the frozen daily SEC snapshot. FRED commits
1,000-observation pages with a durable offset and frozen vintage target, and follows
with catch-up when resuming an old target. Earnings commits one response batch.

Feature calculations retain their per-symbol cache; labels now also cache completed
symbols with keys covering features, prices, actions and label parameters. News,
filings, facts and actions are grouped before repeated symbol operations. Models
already persisted completed horizons; this remains the unit of training recovery.
A partially trained horizon or incomplete derived-data cache may be recomputed.
Individual providers still expose finite response sizes (e.g. a SEC companyfacts
response); full-universe peak RAM and live provider timing remain locally unmeasured.

Brief repeated calls reuse covered event snapshots for `event_refresh_minutes`
(default 15). Later polls still fetch the established 35-day action / 7-day news
correction overlap and deduplicate; this deliberate overlap is not a new historical
bootstrap. The API has no guaranteed late-revision coverage beyond that lookback.
HTTP transient retries have bounded exponential backoff and jitter. Exhaustion
leaves durable progress and a failed stage; there is no unattended auto-restart loop.

Each stage prints its name/start/completion, periodic counts, pages, skips,
insertions, errors, elapsed time and observed rate. Feed totals are unknown, so no
invented percentage or wall-clock completion ETA is shown. Rate excludes records
committed in earlier attempts. Final output includes a stage summary.

## QQQ and identifier diagnostics

The old name classifier rejected `Invesco QQQ Trust, Series 1`: it contained neither
ETF nor Common/Ordinary Stock. Classification now recognizes explicit ETF metadata,
ETF descriptions and listed investment-trust/Trust-Series share structures, with the
same exchange, active/tradable, disallowed product and liquidity gates. There is no
QQQ allowlist. Unknown generic trusts remain unclassified. Distinct active asset IDs
with the same ticker remain ambiguous; inactive/prior ticker observations do not
create active ambiguity. Duplicate snapshots of the same asset ID are consolidated
with active metadata preferred over an inactive copy; conflicting same-status
metadata quarantines that identity and counts toward the systemic failure budget. Unrelated corporate-action/provider identifiers cannot
poison the ticker namespace.

The expected-name QQQ failure is reproduced in tests. **John's actual QQQ row has not
been supplied**, so an additional metadata/quarantine/history-owner issue cannot be
ruled out. `stox diagnose --deep` includes its actual resolution reason. There is no
claim that the precise 438 -> 581 change has been determined: different asset
snapshots, event-identifier pollution and changed eligibility decisions are possible.
Current failure-reason counts separate intended candidates from excluded/inactive
assets. Real diagnostics are needed to attribute that difference.

## Database size and maintenance

2.70 GiB alone is not proof of duplicates. The existing primary keys exclude exact
identical record/identifier keys. Payload versions, typed event references and their
indexes all consume space. Timestamp-only ticker observations and derived annotation
variants can add avoidable history; they are retained because deleting them blindly
would discard observed provenance. New writes prevent those sources of avoidable
growth. Action receipts add compact keys, not another copy of each full payload.
The repair makes no unsupported claim about which object dominates this live DB.

`stox status` is read-only: no Store initialization/migration, provider calls,
Parquet access, directory traversal, row-count scans or dbstat. It uses indexed latest
run/stage queries, small metadata tables, file sizes and page-count/free-list pragmas.
The writer-lock probe distinguishes a live writer from a stale `running` row after
an unclean exit. Cached universe/warehouse summaries expose their observation time.
Schema-2 status immediately reports that an upgrade is needed, without scanning it.

`stox diagnose --deep` explicitly scans table row counts, record versions vs distinct
provider IDs, identifier groups, repeated ticker observations, failure reasons and
SQLite dbstat sizes/unused bytes for tables and indexes. `--integrity` requests a full
integrity check and returns a failure exit code if it fails. Stop bootstrap before
these optional scans. They may take minutes on large external storage; ordinary
status does not run them. Share this JSON to investigate the actual 2.70 GiB footprint.

Optional maintenance, after stopping STOX and closing other DB readers:

```bash
python3 - <<'PY'
from pathlib import Path
import subprocess
subprocess.run([str(Path('.venv/bin/python').absolute()), '-m', 'stox', 'compact', '--vacuum'], check=True)
PY
```

Compaction holds the writer lock, verifies integrity, requires conservative free
space (twice the DB size plus 500 MB), checks that WAL checkpointing is not blocked,
VACUUMs only on this explicit command, then verifies integrity again. It removes
no records. It can reclaim unused pages but cannot shrink legitimate live data.

## Exact local upgrade and resume

First press Ctrl+C once in the old bootstrap terminal and wait for its shell prompt.
Close any old status process too. Keep the same mounted data drive and config.
From your existing repository directory (never a fresh empty data directory):

```bash
python3 - <<'PY'
from pathlib import Path
import subprocess

def run(*args):
    subprocess.run(args, check=True)

run('git', 'pull', '--ff-only')
run('bash', 'scripts/setup.sh')
python = str(Path('.venv/bin/python').absolute())
run(python, '-m', 'stox', 'upgrade')
run(python, '-m', 'stox', 'diagnose', '--deep', '--integrity')
run(python, '-m', 'stox', 'bootstrap')
PY
```

Use the same `--config /path/to/config.toml` / `--root /path/to/.stox` options before
`upgrade`, `diagnose` and `bootstrap` if your original command used those overrides.
Existing `STOX_HOME`/`STOX_CONFIG` environment overrides are respected. No secret value
is printed by these diagnostics. The optional diagnostic step can be run separately
and pasted back before bootstrap if desired.

In a second terminal, from the same directory, fast status is:

```bash
python3 - <<'PY'
from pathlib import Path
import subprocess
subprocess.run([str(Path('.venv/bin/python').absolute()), '-m', 'stox', 'status'], check=True)
PY
```

No runtime files belong in Git. A new PC needs both source and a safely stopped copy
of the existing runtime directory/config (credentials transferred separately).

## Verification scope

Tests include large synthetic actions, per-page transaction bounds, in-page rollback,
provider failure, token expiry/repetition, durable cursor restart, legacy migration
and backfill interruption, raw revisions and first-release preservation, exact CUSIP
`09175M861`, benchmark resolution and namespace separation, cached SEC response
recovery, FRED offset recovery, bounded SQL work for status, and explicit compaction.
A synthetic full engine run fails during actions, restarts from its cursor, produces
all four trained horizons/reports, and reuses ingestion/models on another run.
Live credentials and the actual multi-GB database were not available here.
