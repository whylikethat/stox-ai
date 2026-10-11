# Probability-first weekly forecasting upgrade

This is an additive code upgrade. Schema 4, raw data, holdings/watchlist, old models and immutable predictions remain intact. Normal operation is still `stox run`. No history bootstrap is required. Initial feature-cache rebuilding takes longer once; subsequent identical inputs reuse Parquet caches. Historical labels are rebuilt only when evaluation is due, forced, or selected inputs become incompatible. Normal inference still settles matured prospective forecasts. Existing compatible champions stay active until the normal retraining policy or explicit `--retrain` evaluates challengers. New feature availability alone does not replace the champion.

## Audited production report

Reference: `2026-10-11T120859.745055_0000-8a6c683f/report.html` on John's external drive. Size **95,573,640 bytes**. It contained 33 `<pre>` blocks, 32 detail accordions and 1,068 provider-health entries. All four models used price features only and were unvalidated. 20/30/60D Brier scores were worse than their base-rate benchmarks; 90D marginally beat its benchmark but lacked a reliable qualification threshold. BWET 90D ranked first with P(gain) 50.4128%, expected net 24.8940%, loss>10% 49.5872%.

Root causes:

* Ranking treated a wide calibration uncertainty interval as a tie, allowing expected return to override materially different gain probabilities.
* Independent threshold classifiers, mean regression and quantile regression could disagree. Monotonic threshold probabilities alone did not make the return statistics coherent.
* Enrichment requires 40% historical development coverage and a 0.005 development Brier+ECE improvement. A recent news collection or newly enabled source cannot provide a decade of point-in-time evidence. Price-only is a legitimate outcome, not a reason to bypass ablation.
* HTML directly serialized complete metadata, all research rows and repeated per-symbol evidence. Security-request rows marked INACTIVE were historical diagnostics, not proof that all those tickers were currently inactive.

## Ranking and reporting

Within qualification and consistency categories, order is calibrated gain probability, loss>10%, loss>20%, agreement, independent calibration support, expected return, median, liquidity, then stable symbol/horizon tie-breakers. Conflicting research remains below internally consistent research. No randomness, arbitrary return bonuses or broad probability tie bands are used. Rank is not validation.

The exact existing leaderboard HTML renderer, columns, percentages and styling are retained. Human HTML has no raw JSON or ticker accordions. Compact run/provider, validation and prospective/backtest tables replace dumps. Corporate-action warnings are counted, with relevant Top-20 notices retained. Full machine detail remains in JSON. Terminal context is summarized by counts rather than dumping entire provider records. Evidence is indexed once per run, and reference-based explanations are inferred in a batch; both optimizations preserve their numerical meaning.

`reports/comparison.json` is a small atomic prior-run snapshot, partitioned by run mode. Current and previous Top 20 in 30D and across horizons yield NEW/UP/DOWN/UNCHANGED/DROPPED rows. Probability changes are percentage points. The first upgraded run can initialize from existing latest.json; later runs read only the compact snapshot. It never recomputes previous predictions using current data. A rank marked UNCHANGED can still have numerical changes. Only known model/session changes are attributed; no causal story is invented.

## Causal feature challengers

The original price baseline is retained. Independently evaluated additions:

* Advanced price: 10/40-session momentum, momentum acceleration, 20/100-session moving-average distance, 50/200-average slopes, short/medium volatility ratio, 60-session return skew/tail frequency, volume acceleration, liquidity variation and gap mean. Existing 5/20/60/120 momentum, downside volatility, drawdown, liquidity and trend features remain.
* Market: QQQ/IWM relative strength where cached history exists, beta-adjusted momentum, benchmark volatility, QQQ-vs-SPY context and current-universe breadth above 50/200 averages. Breadth is computed before row sampling. Current-universe survivorship limitations remain explicit. No unsupported historical sector map is inferred.
* News: timestamp-bounded 1/3/7/30-day counts, abnormal-volume ratio, bounded deterministic headline polarity, regulatory, financing, earnings/guidance and M&A flags. Keywords are noisy proxies, not verified events or generative sentiment. Initial coverage warmup remains missing, not falsely zero.
* SEC/fundamentals: existing accession-aware annual revenue growth/margins/assets/leverage retained; filing frequency, 8-K frequency and recency form a separate candidate family, no longer mixed into news. Comparable fiscal durations and availability constraints remain.
* Macro: existing vintage-aware ALFRED features plus yield-curve spread.

Historical earnings surprises, verified future earnings, sector identity history, analyst revisions and options require source evidence not supplied by the current calendar-only earnings endpoint. Missing fields remain missing/context-only. There is no claim these unavailable families have been validated.

## Model and distribution challengers

Logistic and histogram models remain. A bounded deterministic ExtraTrees classifier (48 trees, depth 10, leaf minimum 40) is added. Each major available feature family is tested separately against the price baseline; features are not concatenated blindly. Sigmoid calibration and monotone exceedance projection remain. Isotonic/regime calibration and segmented models are not promoted without a separate evaluation.

The coherent challenger uses the same calibrated exceedance probabilities with empirical training-only return supports within seven threshold bins. Their mixture produces the mean and 10/50/90 quantiles. Empty bins use documented midpoint/tail fallback supports; they are not measured tail distributions. This approach makes median direction and threshold probabilities coherent by construction, but high gain probability can still legitimately coexist with negative expected return under asymmetric loss sizes. The conservative consistency gate remains.

The coherent challenger is eligible only when development-fold conflict rate improves and return MAE deteriorates by no more than 5%; probability Brier/ECE are unchanged for the same classifier. Existing independent-return models are not overwritten. Tail/interval holdout diagnostics remain visible. No accuracy improvement is inferred from consistency alone.

Temporal design: 70% development (internally purged train/calibration and two walk-forward folds), next interval up to 80% for promotion, final 20% holdout audit. Label endpoints and five-day embargo enforce horizon-dependent purging. Selection/thresholds use development. Incumbent comparisons use the promotion interval, and exclude dates through the incumbent's already inspected holdout end. Thus existing mature champions often require genuinely new evidence before replacement; the system does not repeatedly tune on the same historical holdout. Initial models still require the existing strict holdout qualification checks. Already inspected historical outcomes are retrospective diagnostics, not a newly untouched prospective test.

## Optional paid providers

`SignalAdapter` defines a future licensed adapter contract. `enable_analyst_signals=false` and `enable_options_signals=false` are the defaults. Accepted locally cached signals require symbol, numeric values, source URL, license confirmation, publication availability and observation timestamps. Observation time is conservatively enforced. Intrinio/Zacks and ORATS are intended future adapters; no live commercial connector, payment, credential requirement, unlicensed scraping or Danelfin dependency is introduced. Unknown/no credentials means missing features and the core price path continues.

## Installation / operation

Keep the existing active config and `.secrets/providers.env`. Do not replace them with an example profile. After source changes are committed and the checkout is up to date:

```bash
cd /run/media/unknown/MAXIMAL/stox-ai
git pull --ff-only
bash scripts/setup.sh
source .venv/bin/activate
stox doctor --live
stox run
stox run
```

No migration or bootstrap is required. Optional PDF disclosure extra remains `python -m pip install -e '.[disclosures]'`. Explicit `stox run --retrain` performs bounded model evaluation and can take substantially longer; it is not required for the report/ranking upgrade and does not guarantee promotion. Default evaluation algorithms can be configured with `model_algorithms = ["logistic", "histogram", "extra_trees"]`.

Same completed session, same selected feature inputs and same champion produce identical forecasts. New sessions/events only change probabilities when selected model inputs change. No guarantee of different weekly picks or of validated opportunities is made.
