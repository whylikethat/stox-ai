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
