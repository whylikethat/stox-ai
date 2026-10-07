# Acceptance record

This record distinguishes implemented offline functionality from unproven live behavior and remaining specification gaps. The repository must not be described as a fully live-validated investment system.

| Area | Offline implementation / evidence | Remaining limitation |
|---|---|---|
| Package, setup, CLI, paths, secrets | Python package, pinned environment, named CLI commands, safe templates | Pinned installation needs local Kali check |
| Market/news/actions ingestion | HTTP adapters, pagination, retries, durable checkpoints, idempotent merges, revisions | Actual account entitlements and historical coverage need live doctor/bootstrap |
| SEC and macro | Submission history, accession-based facts, vintage-aware ALFRED, conservative availability | Filing text semantic summaries and exhaustive bulk ingestion optimization absent |
| Optional enrichment | Budgeted earnings calendar | Listing/delisting enrichment and broad earnings-estimate endpoints not implemented |
| Universe | Active/inactive metadata; conservative type and dollar-liquidity filters | No certified historical universe or full symbol-successor reconstruction |
| Corporate actions | Ordinary splits and cash distributions; unsupported events quarantine | Automatic merger/spin-off/successor valuation not implemented |
| Features | Causal price/volume, cross-sectional context, as-of facts/news/macro; symbol caches | Industry-relative features absent; larger universes sampled; full-universe RAM/runtime unmeasured |
| Models | All four horizons, two algorithm families, walk-forward validation, calibration, downside and quantile estimators, registry | Real predictive usefulness and extreme-tail calibration not established |
| Decisions | Two leaderboards, Top-3, transparent ties, no-forced-pick rules, earnings unknown warnings | Zero qualifying opportunities is possible for long periods |
| Forecast tracking | Immutable payloads, pending next-open entry, independently settled horizons, total returns | Daily SIP prices are paper references, not exchange-auction certification |
| Holdings | Add/list/remove, original forecast linkage, P/L and deterioration, supporting evidence | No brokerage reconciliation; tax and execution fees excluded from actual holding P/L |
| Reports | Terminal, HTML, JSON, Markdown, self-contained independent-review Markdown | Rendering does not establish forecast accuracy |
| Storage/recovery | Locks, page-level durability, compressed Parquet, bounded logs/artifacts, budgets | Large fundamental/event payloads still in SQLite; no mandatory background processes |
| Tests | Socket-blocked unit/integration suite and four-horizon synthetic end-to-end run | No credentialed provider calls; no real performance claims |

The full user specification is retained in `BUILD_SPECIFICATION.md` for future audits. Unsupported items above are not represented as completed by stubs, invented data or fabricated validation results.


## 2.0.3 bootstrap performance/resume repair — 2026-10-07

- Full offline suite: **103 passed** (133.58 seconds on the development runner).
- New recovery module contains **25 tests**, including a full-engine interruption,
  resume through all four horizons and reports, and a second idempotent run.
- Transaction benchmark: **11,000 input / 10,000 unique actions**, 30,000 typed
  event identifiers, **11 page commits / 17 total commits** including job/stage
  bookkeeping, **1.211 seconds** on local synthetic storage. The old design would
  make roughly four transaction commits per input action for these three identifier
  fields plus its payload. This is transaction-count evidence, not an external-drive
  or live-provider runtime promise. FULL synchronous WAL remains enabled.
- Status tested with 50,000 event rows and a SQL VM instruction budget; it performs
  no provider calls, Parquet reads, schema migration or recursive storage walks.
- Existing SIP/FRED doctor and `09175M861` regressions remain covered.
- Compile checks and `git diff --check` pass. No separate lint/type-check gate is
  configured in this repository.
- Actual provider access, John's multi-GB database size attribution, the precise
  historical identifier-count increase and actual QQQ metadata remain unverified.
  The [upgrade guide](BOOTSTRAP_REPAIR.md) provides read-only diagnostics and
  non-destructive commands. Legacy rows are reused but cannot prove missing old
  provider pagination positions; the required one-time verification replay is
  documented rather than falsely claimed to be skippable.
