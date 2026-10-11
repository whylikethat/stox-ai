# STOX 2.3.1 — corporate-action roles, research data quality and report size

This correction addresses defects found in a read-only audit of the user's 2.3.0 production run. No validation threshold is relaxed and no predictive improvement is claimed.

## Corporate actions

Merger records distinguish acquirer and acquiree roles. Previously, every resolved ticker on an action was passed into the share-return calculation. A cash or stock acquisition therefore excluded the acquirer's whole feature history, even though the conversion terms apply to the acquired shares. The return path now omits only clearly acquirer-only merger records. The target, missing target identity, equal acquirer/acquiree identifiers and unknown roles remain conservative. These events remain available as contextual evidence for both parties. CUSIP values are never treated as ticker lookup requests.

Stock dividends use their supplied `rate` multiplier, separately from forward/reverse splits' `new_rate / old_rate`. Missing, nonfinite or ambiguous sub-one stock-dividend rates remain unresolved. Cash entitlements, event ordering and ex-date entry behavior are unchanged. Spin-offs, unit conversions and other unsupported reorganizations remain excluded; no guessed settlement proceeds or history stitching is introduced.

The provider's distinct structures can be inspected in the [official Alpaca SDK schema](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/models/corporate_actions.py).

Feature version `causal-v5` invalidates old feature caches. Existing price Parquet and database records remain intact. Compatible models continue inference, and frozen trial predictions already issued are not rewritten. Restored universe members can affect current cross-sectional features and rankings. Existing backtests describe the original training universe; expanded coverage is not proof of improved accuracy. Future evaluations retain the existing temporal and qualification rules.

## Ranking

Qualified opportunities remain first. Among research forecasts, securities with adequate observed data precede securities with insufficient history, stale/missing sessions, low liquidity or other security/data exclusions. Consistency and calibrated probability then determine order, followed by the existing tie-breakers. Every research row remains available, including data-limited candidates. Probabilities and return estimates are not overwritten to accomplish reranking. Status labels make limited data explicit.

## Report export contract

New JSON exports declare `report_schema_version: 2`. The existing numerical row arrays remain available. Repeated `catalyst_context` and candidate `evidence` objects are replaced by `evidence_ref`, a symbol key into the root `evidence_by_symbol` dictionary. `stox.reporting.evidence_for(report, row)` reads either legacy inline evidence or new references. Full Markdown stores this evidence dictionary once; the independent-review export includes the relevant highlighted symbols. HTML retains its compact tables and data-limited status labels.

An in-memory conversion of the audited production report reduced JSON from 160,109,477 bytes to 32,943,062 bytes (about 79%). Every numerical field, exclusion and evidence record was compared against the original. This is an export change only: older reports and persisted forecasts are not migrated or deleted.

## Installation and normal operation

Version 2.3.1 uses the existing schema 5; no database migration is required. Installation backs up changed source and the runtime database, preserves user config and secrets, and does not restore report directories the user deleted. Continue `stox run` normally. The first run rebuilds feature caches; subsequent unchanged inputs can reuse them. Restored securities and corrected cross-sectional features may create new unique forecast snapshots, while existing snapshots remain immutable.

## Verification

- Complete offline suite: **193 passed in 705.18 seconds (11m45s)**, with no deselected tests. Focused correction/ranking/report/identifier tests also passed (59 tests).
- Read-only application of the corrected rules to the audited stored actions removed the blocking errors for 77 of the 119 excluded securities; 42 remained unresolved. This includes restoring MSFT, NVDA, AMD, AMZN and CBSH, without manufacturing target-side merger or spin-off returns.
- Existing report conversion was checked field-by-field for numerical forecasts, exclusions and evidence; all were preserved. New tests also check ex-date entitlements, stock-dividend/cash sequencing, ambiguous identities, unknown actions, feature-building integration, deterministic quality ranking and all export formats.
- Installed `stox status` completed successfully in 0.149 seconds while the live writer was active.
- No schema migration is required. Source and SQLite backup: `.stox-local/correction-backup-20261011T205024Z/`; database file `state-before-correction.sqlite`.

The installed production run `2026-10-11T205216.903959_0000-9671760e` exited successfully. Results: **3,832 research forecasts across 958 securities**, up from 3,524 across 881; **42 unresolved notices**, down from 119; **zero validated opportunities**. BLLN remained in research at 30D rank 932, outside the Top 20. There were 957 newly persisted symbol snapshots following changed coverage/inputs. Comparing the backup against the resulting database confirmed that all **881 previous forecast snapshots and 3,416 previous paired trial predictions** remained byte-for-byte unchanged in their stored rows. No earlier entries, outcomes or holdings were missing or modified.

The new production JSON measured **37,015,436 bytes**, approximately 77% smaller than the audited prior 160 MB report despite broader coverage. HTML measured 40,372 bytes. News, SEC, FRED, Alpha and earnings-history health were PASS; public disclosures reported OK. Existing contradictions remain visibly research-only: 1,314 current forecast rows were flagged, rather than rewritten or qualified. No accuracy or profitability improvement is claimed.
