# Architecture

STOX-AI is a single-user local Python package. `stox run` is the orchestrator; the only network operations are GET requests to approved data-provider APIs. There is no account, order, allocation, mail or scheduler component.

| Boundary | Implementation | Persistence / guarantees |
|---|---|---|
| Configuration | `config.py` | TOML, environment, local secrets; paths resolve relative to config |
| Calendar | `calendar.py` | XNYS holiday and early-close schedule; timezone-aware timestamps |
| Provider transport | `providers/http.py` | Timeouts, per-host throttling, bounded retries, redacted errors |
| Adapters | `providers/` | Alpaca, SEC, FRED/ALFRED, optional Alpha Vantage |
| Ingestion | `ingestion.py`, `streams.py` | Stable symbol scopes; atomic page/cursor receipts within bounded date windows |
| Universe | `security.py`, `universe.py` | Typed identity and authoritative query authorization; conservative instrument, liquidity and history gates |
| Storage | `storage.py` | SQLite WAL, process lock, compressed Parquet, DuckDB summaries |
| Corporate actions | `actions.py` | Explicit unit/cash accounting; unknown transformations quarantine |
| Features / labels | `features.py` | Causal wealth index, availability joins, calendar-day targets |
| Modeling | `models.py` | Temporal validation, separate calibration, holdout, challenger registry |
| Decisions | `ranking.py` | Validation qualification and transparent probability-equivalence groups |
| Forecasts | `predictions.py` | SQL-trigger immutability; entry and per-horizon outcomes are separate append-only records |
| Holdings | `holdings.py` | Manual entry, retained history and descriptive deterioration reviews |
| Reports | `reporting.py` | Local HTML, JSON, Markdown and independent-review package |
| Operations | `cli.py`, `doctor.py`, `progress.py`, `diagnostics.py` | Durable stages, read-only status, opt-in forensic scans/compaction, upgrade, doctor, holdings, demo |

## Transaction boundaries and recovery

Each downloaded bar page is validated and atomically merged into its symbol's Parquet file. A price checkpoint advances only after complete pagination and verification that durable bars contain the target completed session. Legacy empty/overstated checkpoints are audit-invalidated without removing data. A partial failure leaves prior page data durable but not marked complete, so replay is idempotent. Event revisions use `(kind, provider record ID, payload hash)` uniqueness. Model files use temporary files and atomic rename before registry insertion. Run status identifies failure separately from last success. An advisory filesystem lock serializes writers.

Official forecast payloads are inserted once; SQL triggers reject updates and deletes. Actual paper entry and outcomes are inserted into separate immutable tables. New forecasts are persisted before exports so an export failure cannot erase issued numerical results. AI export is isolated. Last-report aliases update atomically; a failed core update does not overwrite trustworthy reports.

## Memory and incremental work

Price features are cached per symbol and invalidated by data/action fingerprints. A changed symbol recomputes its bounded history, while unchanged symbols reuse caches. Before assembling large-universe development data, stable symbol/date hashing samples nonbenchmark rows under the configured row target. Momentum and volatility are computed on full per-symbol sequences before sampling. SPY/QQQ remain complete for benchmark joins. Training also enforces a row cap. This is a bounded local design; production full-universe RAM/runtime have not been measured.

Current cross-sectional ranks on sampled historical dates reflect the sampled observed universe; the latest date retains every observed symbol. Labels remain tied to real full-history entry/settlement rows, not positions in a sampled table.

SQLite event/fundamental state may grow materially on large universes. A future high-volume optimization should migrate normalized bulk events/facts into partitioned Parquet while keeping transactional indexes and provenance. The initial implementation does not claim that this optimization has already been performed.

## Audit and retention

Every official forecast retains model IDs, calibration/evaluation metadata, feature version, universe/data fingerprints, source health and information cutoffs. Model artifacts referenced by official forecasts are retained. Unreferenced older artifacts are pruned while registry metadata persists. Historical bars/events are not automatically deleted. Logs rotate; cache temporaries are disposable. Forecasts/outcomes are never retention targets.


## Security master and query boundary

`security_master` is keyed by Alpaca asset ID, with distinct raw provider symbol and nullable validated market-data ticker. `security_identifiers` carries typed values, sources, roles, effective and observation times. `security_snapshots` preserves changed decisions. `price_history_owners` binds ticker archives to asset IDs; `security_quarantine` persists isolated provider rejection with a bounded retry time. Additive schema-2 migration leaves original datasets and immutable forecast/outcome tables intact.

All production bars calls take `MarketDataSymbol` references returned by the master. Validation combines asset class/exchange/security type/status/tradability, unique identity, typed-ID conflicts and broad syntax safeguards; passing a regex alone never authorizes a symbol. Ingestion and engine share this master. Holdings remain stored even if unresolved, but cannot authorize queries or healthy reviews. Features and labels require resolution; ranking checks master eligibility. Reports consume those filtered outputs. Historical forecast settlement reads retained local archives only and never initiates provider symbol queries.

Corporate-action annotations attach separately typed references to the original event; unknown/private distribution securities stay event provenance. SEC enrichment starts with resolved tickers and attaches CIKs to asset identity. News is fetched globally and joins only validated feature tickers. Neither path creates assets. One-off invalid symbols are isolated; aggregate failure budgets and existing coverage/benchmark gates prevent a widespread universe defect from silently producing forecasts.


## Schema 3 ingestion recovery

See [the 2.0.3 repair record](docs/BOOTSTRAP_REPAIR.md) for migration, page atomicity,
legacy-state limitations and exact commands. SQLite helpers join caller-owned
transactions. Corporate actions and news persist every provider page and next cursor
in one FULL synchronous WAL transaction; 31-day windows bound expired-token replay.
Raw action receipts preserve existing revisions and skip repeat normalization.
A resumable rowid-based legacy backfill creates those receipts without inventing
proof of old feed completeness. No runtime data or historical observations are deleted.

SEC commits bounded row batches and reuses cached response files; FRED retains page
offsets and frozen vintage cutoffs. Features and labels cache completed symbols;
models cache completed horizons. Read-only status consults indexed stage/run metadata
and saved universe/warehouse summaries, with a writer-lock liveness probe.
