# STOX 2.3: forward model evaluation and bounded enrichment

Normal operation remains `stox run`. No new paid account, brokerage connection, watchlist population or history reset is required. Existing config values remain active; new defaults are three earnings-history symbol requests per run and at most 60,000 eligible rows per horizon when evaluating a challenger. The existing Alpha Vantage daily budget still applies. Sector reference histories add at most eleven ETFs to the selected modeling set, not thousands of full-history downloads.

## What changed

The previous historical promotion interval could be entirely earlier than the incumbent's already inspected holdout end. This left no eligible comparison dates. Existing champions now remain active while one frozen challenger per horizon issues paired forward predictions alongside them. Historical holdout tests remain diagnostics and qualification checks; they no longer repeatedly select a replacement on old outcomes.

Trials have a persisted, fixed policy: the configured minimum samples and independent blocks, calibration ceiling, transaction friction, and a single planned comparison. Each symbol's first prediction for a given next-open entry is retained. Entry prices are frozen once observed, outcomes are settled using the same corporate-action-aware net-return definition as public forecasts, and duplicate runs insert nothing twice. Offline/synthetic runs cannot issue these live trial predictions. No trades are executed.

Promotion requires a positive lower confidence bound for paired block-level Brier improvement (one-sided Student t, corrected across the configured horizons), calibration no worse than the incumbent and configured ceiling, and return MAE deterioration of no more than 5%. This statistical test is approximate, not a guarantee. It is performed once after the fixed collection window matures. Failed or insufficient trials retain the incumbent; no repeated checking until a lucky pass. A different challenger can be evaluated later on a new forward cohort. Repeated research over many cohorts still entails selection risk.

Qualification remains separate. A promoted research model does not become validated merely by beating another weak model. Its pre-existing holdout validation, probability threshold, calibration support, tail-risk, model-agreement, data and consistency gates still apply.

With the default eight independent blocks, useful evidence is not eight runs or eight weeks. The fixed collection window is eight times (horizon + five calendar days), followed by outcome maturity. For 20D this is roughly eight months; for 90D it can exceed two years. Missing observations can yield insufficient evidence; the trial also requires the configured settled-outcome coverage so unresolved outcomes cannot simply disappear from the comparison. Monthly/weekly monitoring is still useful, but there is no promised date for validated opportunities.

Evaluation attempts are checkpointed. A collecting trial prevents repeated retraining, including repeated `--retrain` calls; compatible champions continue normal inference. One initial evaluation of legacy models is scheduled after upgrading, using the existing mature historical dataset. Later evaluations require the normal cadence and new-label budget. This first evaluation can be slower; normal subsequent runs stay incremental. The independent block/sample rules are not weakened.

## Sources, availability and indicators

* **Alpaca** remains the core price/volume/action source. Trailing 126-session return correlation to XLB/XLC/XLE/XLF/XLI/XLK/XLP/XLRE/XLU/XLV/XLY selects a sector-ETF affinity proxy, with a minimum correlation and sample count. Relative momentum and ETF momentum are separate challenger inputs. This is explicitly a price-derived proxy, not asserted historical sector membership. No retrospective mapping of current sectors is performed.
* **SEC company facts** add accession-matched annual operating margin, cash/assets, free-cash-flow/assets and share-count growth. Missing capex is not assumed zero; mismatched accessions/fiscal periods are not combined. Filing availability controls every feature. [Official SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
* **Alpha Vantage EARNINGS** adds quarterly actual/estimated EPS, surprise, fiscal end and reported date. The publication date bound and local observation timestamp are separate. History received today is not retrospectively treated as a pristine historical vintage. Surprise, earnings age and recent positive-surprise fraction become usable only after observation. Calendar dates remain unconfirmed context, not fabricated confirmed events. Common stocks are queried through the security master; per-symbol failures have attempt checkpoints and cannot permanently block later symbols. Quota/entitlement failures remain optional. [Official Alpha Vantage documentation](https://www.alphavantage.co/documentation/). Coverage/entitlement depends on the existing account; this release purchases nothing.
* **Licensed analyst/options exports** can now be imported with `stox import-signals --file export.json`. This is a local adapter input, not an Intrinio, Zacks, ORATS or Danelfin network connector. Imports require explicit license confirmation, HTTPS source URL, an authoritative ticker, timezone-aware publication time and finite supported values. First local observation is enforced and values expire after 30 days. Leave `enable_analyst_signals` and `enable_options_signals` false unless you supply licensed data. The software does not grant redistribution rights.

Example licensed local input (example values, not market data):

```json
[{"symbol":"AAPL","family":"options","license_confirmed":true,"source_url":"https://your-licensed-provider.example/export","available_at":"2026-10-11T12:00:00Z","values":{"options_iv30":0.3}}]
```

Existing free public transaction disclosures remain contextual. House/Senate usage restrictions still apply. No new politician-trading model or paid scraping service is introduced.

## Audit and reports

The existing prediction tables stay intact. A compact model-progress table shows trial state, mature samples, independent blocks and the decision/reason. A data audit shows date coverage, revision exclusions, missing recent sessions, insufficient history, feature-family coverage and consistency conflicts. Prospective Top 3/Top 20 win rate, mean net return, major-loss frequency, non-overlapping cohorts and drawdown are separate from historical backtests and qualified/research cohorts.

New forecast snapshots preserve per-horizon rank for those prospective statistics; missing ranks in older records are not reconstructed with current data.

Historical and prospective returns use next regular open, calendar-day horizons, first eligible closing session, distributions/splits and configured round-trip friction. Unknown corporate actions remain exclusions. Current-universe survivorship limitations remain visible. More feeds do not establish predictive skill; no new family is automatically promoted.

## Storage and migration

Schema 4 -> 5 adds compact trial definitions, paired forecasts, frozen entries and outcomes. Existing tables, immutable forecasts and raw history are retained. Migration is transactional and automatic when a writer opens the store; `stox status` remains read-only and local. New price-derived feature caches use `causal-v4`; original compatible model files still load. Active trial model artifacts are retained by cleanup. Reports retain the existing bounded retention policy; bulk prices/features remain Parquet.

## Operation

After installation, continue:

```bash
cd /run/media/unknown/MAXIMAL/stox-ai
source .venv/bin/activate
stox run
```

No bootstrap or manual retraining loop is required. No automated schedule is installed: forecasts and settlement advance when you run STOX. A failed optional provider does not disable compatible core-price inference. Always distinguish successful software operation from demonstrated predictive accuracy.
