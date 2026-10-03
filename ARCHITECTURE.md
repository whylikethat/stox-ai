# Architecture

STOX-AI is a single-user local Python package. `stox run` is the orchestrator; the only network operations are GET requests to approved data-provider APIs. There is no account, order, allocation, mail or scheduler component.

| Boundary | Implementation | Persistence / guarantees |
|---|---|---|
| Configuration | `config.py` | TOML, environment, local secrets; paths resolve relative to config |
| Calendar | `calendar.py` | XNYS holiday and early-close schedule; timezone-aware timestamps |
| Provider transport | `providers/http.py` | Timeouts, per-host throttling, bounded retries, redacted errors |
| Adapters | `providers/` | Alpaca, SEC, FRED/ALFRED, optional Alpha Vantage |
| Ingestion | `ingestion.py` | Stable symbol scopes; per-feed checkpoints only after complete pagination |
| Universe | `universe.py` | Conservative instrument classification, liquidity and history gates |
| Storage | `storage.py` | SQLite WAL, process lock, compressed Parquet, DuckDB summaries |
| Corporate actions | `actions.py` | Explicit unit/cash accounting; unknown transformations quarantine |
| Features / labels | `features.py` | Causal wealth index, availability joins, calendar-day targets |
| Modeling | `models.py` | Temporal validation, separate calibration, holdout, challenger registry |
| Decisions | `ranking.py` | Validation qualification and transparent probability-equivalence groups |
| Forecasts | `predictions.py` | SQL-trigger immutability; entry and per-horizon outcomes are separate append-only records |
| Holdings | `holdings.py` | Manual entry, retained history and descriptive deterioration reviews |
| Reports | `reporting.py` | Local HTML, JSON, Markdown and independent-review package |
| Operations | `cli.py`, `doctor.py` | Setup, run, report, status, doctor, holdings, isolated demo |

## Transaction boundaries and recovery

Each downloaded bar page is validated and atomically merged into its symbol's Parquet file. A checkpoint advances only after the complete symbol/feed request succeeds. A partial failure leaves prior page data durable but not marked complete, so replay is idempotent. Event revisions use `(kind, provider record ID, payload hash)` uniqueness. Model files use temporary files and atomic rename before registry insertion. Run status identifies failure separately from last success. An advisory filesystem lock serializes writers.

Official forecast payloads are inserted once; SQL triggers reject updates and deletes. Actual paper entry and outcomes are inserted into separate immutable tables. New forecasts are persisted before exports so an export failure cannot erase issued numerical results. AI export is isolated. Last-report aliases update atomically; a failed core update does not overwrite trustworthy reports.

## Memory and incremental work

Price features are cached per symbol and invalidated by data/action fingerprints. A changed symbol recomputes its bounded history, while unchanged symbols reuse caches. Before assembling large-universe development data, stable symbol/date hashing samples nonbenchmark rows under the configured row target. Momentum and volatility are computed on full per-symbol sequences before sampling. SPY/QQQ remain complete for benchmark joins. Training also enforces a row cap. This is a bounded local design; production full-universe RAM/runtime have not been measured.

Current cross-sectional ranks on sampled historical dates reflect the sampled observed universe; the latest date retains every observed symbol. Labels remain tied to real full-history entry/settlement rows, not positions in a sampled table.

SQLite event/fundamental state may grow materially on large universes. A future high-volume optimization should migrate normalized bulk events/facts into partitioned Parquet while keeping transactional indexes and provenance. The initial implementation does not claim that this optimization has already been performed.

## Audit and retention

Every official forecast retains model IDs, calibration/evaluation metadata, feature version, universe/data fingerprints, source health and information cutoffs. Model artifacts referenced by official forecasts are retained. Unreferenced older artifacts are pruned while registry metadata persists. Historical bars/events are not automatically deleted. Logs rotate; cache temporaries are disposable. Forecasts/outcomes are never retention targets.
