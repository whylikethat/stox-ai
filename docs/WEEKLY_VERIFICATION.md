# Weekly upgrade verification

All metrics below use real cached data from the external drive, not synthetic prices. The experiment was capped at 40,000 eligible rows per horizon (deterministic thinning); the initial feature panel contained 45,474 rows across 881 securities, producing 175,413 mature horizon labels before per-horizon filtering. These experiments use a revised split and sample, so their scores are not directly comparable to the older production report scores.

Family/algorithm/distribution selection was locked on development before these holdout audits. Auditing all families below did not change the selection or any production champion. Existing production holdouts have already been inspected; these are retrospective out-of-time checks, not a newly untouched prospective test.

| Horizon | Price baseline Brier | Advanced price Brier | Market Brier | Selected development family | Selected holdout Brier | Holdout base Brier | Validated |
|---|---:|---:|---:|---|---:|---:|---|
| 20D | 0.25473 | 0.25486 | 0.25432 | price+market | 0.25432 | 0.24615 | No |
| 30D | 0.25598 | 0.25664 | 0.25646 | price | 0.25598 | 0.24472 | No |
| 60D | 0.25556 | 0.25569 | 0.25841 | price+market | 0.25841 | 0.23744 | No |
| 90D | 0.27247 | 0.27477 | 0.27532 | price+market | 0.27532 | 0.22920 | No |

No challenger passes validation. No new feature family is approved for production promotion by these results. The slight 20D market-family Brier improvement over the matched price baseline is accompanied by worse calibration and does not establish useful validated skill. Other additions did not consistently improve the held-out benchmark. Existing champions are retained.

All four selected experiments used the coherent distribution candidate. Median-direction/probability conflicts were 0% on their holdout rows. That is a consistency result, not a gain in predictive accuracy; expected-return asymmetry can still trigger the conservative gate.

News, filings, fundamentals and macro did not meet historical development coverage for ablation in this copied dataset. Earnings surprises/confirmed dates, historical sectors, analyst revisions and options were unavailable. They are not reported as empirically rejected models or as validated signals.

Live doctor passed all configured providers: Alpaca assets/prices/news/actions, SEC, FRED and Alpha Vantage. Original drive state, raw data and champions were not modified by experiments.

Exact reference HTML: 95,573,640 bytes. Clean rendering of the same report: 27,861 bytes; with probability-first ranking and two prior-run change tables: 44,639 bytes. Original leaderboard columns and renderer retained; zero `<pre>` data blocks and zero `<details>` accordions. Machine JSON retains full details.

## Final acceptance — 2026-10-11

Two consecutive real CLI runs completed with exit 0, using the external drive's active configuration and credentials against an isolated copy of its healthy data. The acceptance config capped any training evaluation at 40,000 rows; inference retained the existing 1,000-name modeling universe. No original runtime data was written.

* First: `2026-10-11T135122.335392_0000-ec283827`.
* Second: `2026-10-11T135551.300999_0000-1dda8764`.
* Both produced **3,524 research forecasts** across **881 securities** and **20/30/60/90D**. The four original champion IDs remained unchanged.
* All research forecast probabilities, expected/median returns, tail probabilities, qualification states and ranks matched across the two same-session runs. The Top 20 also matched. The second run created **zero duplicate snapshots** and every comparison row was **UNCHANGED**.
* First live HTML: **45,122 bytes** (includes changes against the older ranking). Second live HTML: **36,961 bytes** (unchanged Top 20). Reference: **95,573,640 bytes**. Both had zero raw `<pre>` blocks and zero `<details>` accordions; JSON retained all research rows and evidence.
* Probability-first ranking removed BWET from the overall Top 20. Predictions themselves were not rewritten to accomplish the ranking change.
* No model became validated. The 1,217 existing classifier/regression conflicts remain visible and cannot qualify. The coherent challenger's zero median-direction conflicts are experimental, not a claim that production has switched to it.
* A preceding copied-data run was deliberately interrupted with Ctrl-C during ranking. Restart resumed durable ingestion checkpoints and completed both runs without duplicate forecasts. No bulk-history bootstrap ran.

The complete offline suite passed: **164 tests in 760.52 seconds**. After final inference/report optimizations, the focused regression suite passed **54 tests (1 deliberately deselected slow training test)**. The final starter/weekly suite, including the slow end-to-end training test, passed **27 tests in 120.81 seconds**. Tests cover ranking/tails, causal features, deterministic changed-data inference, coherent distribution, leakage protections, optional providers, report preservation/size, prior-run changes, snapshot idempotency, source fallback and disclosure parsing. No network is needed by the offline suite.

## Files and compatibility

Weekly upgrade files: `CHANGELOG.md`, `README.md`, `config.example.toml`, `pyproject.toml`, `src/stox/__init__.py`, `src/stox/config.py`, `src/stox/engine.py`, `src/stox/features.py`, `src/stox/models.py`, `src/stox/providers/optional_signals.py`, `src/stox/ranking.py`, `src/stox/reporting.py`, `tests/test_starter.py`, `tests/test_weekly_upgrade.py`, `docs/WEEKLY_UPGRADE.md`, and this verification document. The commit also preserves the already installed public-disclosure work in `src/stox/cli.py`, `src/stox/ingestion.py`, `src/stox/disclosures.py`, `tests/test_disclosures.py`, and `docs/PUBLIC_DISCLOSURES.md`.

No database schema change or destructive migration is needed: schema 4 remains. Old compatible model files load with the independent-distribution default. Features use a new cache version; compact comparison snapshots are additional report state. The active config, secrets, holdings/watchlist, raw history and immutable forecast records are preserved. Source backups are stored under `.stox-local/source-backup-*` on the external drive before installation. User modifications to `config.production.toml` remain unstaged.

Installation follow-up: the external checkout had stale source-tree `stox_ai.egg-info` version 2.1.0 after the editable installer correctly installed 2.2.0. `scripts/check_setup.py` now verifies distribution metadata in the virtual environment explicitly, so source metadata cannot shadow the installed version. Existing bounded FRED vintage ingestion changes were preserved. Final ingestion/disclosure/weekly regression check: 39 passed.
