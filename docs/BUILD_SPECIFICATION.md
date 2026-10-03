# STOX-AI — FINAL CLEAN-SHEET BUILD SPECIFICATION

## 1. ROLE AND EXECUTION INSTRUCTIONS

Build **STOX-AI** from scratch as a complete, production-quality local investment forecasting and research application.

Use the connected GitHub repository:

`whylikethat/stox-ai`

as the canonical source-code repository.

This is intended to be a comprehensive build, not a prototype, mock-up, scaffold, or architecture-only exercise. Carry the work through implementation, testing, documentation, Git commits, and a usable release.

### Communication with the user

The user's name is **John**.

In **every user-facing progress update and final response**, address the user as **John** at least once.

Do not put John's name into automated STOX-AI reports, generated investment reports, CLI output, logs, datasets, predictions, or AI-review packages.

Keep progress updates concise and useful.

If there is a genuinely blocking ambiguity that cannot reasonably be resolved from this specification, ask **one consolidated batch of questions before implementation**. Do not repeatedly interrupt the build with minor questions. For non-blocking implementation details, make a sound engineering decision, document it, and continue.

Do not require John to provide or upload secret API credentials into this Work session.

Use fixtures, mocks, synthetic data, and sanitized recorded schemas for development and automated tests.

The final project must include a live provider preflight/doctor command that John can run locally with his own secrets after pulling the repository.

---

# 2. PRODUCT MISSION

STOX-AI is a local, on-demand U.S. equity and ETF forecasting system.

Its purpose is to answer:

> **What are the strongest investment opportunities right now, how likely are they to make money, how much might they make, what could go wrong, and have my current holdings gotten better or worse?**

The system is intended for medium-term investing rather than day trading.

John may eventually consider allocating anywhere from approximately **$10,000 to $100,000 USD** to an opportunity.

STOX-AI must therefore emphasize:

1. forecast accuracy;
2. calibrated probabilities;
3. downside awareness;
4. adequate liquidity;
5. point-in-time data integrity;
6. prospective performance tracking;
7. transparent evidence;
8. reproducibility.

STOX-AI is a decision-support system.

It must **not**:

- execute trades;
- connect to a brokerage for trading;
- recommend position sizing;
- automatically allocate capital;
- short stocks;
- trade options;
- promise profits;
- force a recommendation when no sufficiently strong opportunity exists.

John makes all final investment decisions manually.

---

# 3. DEPLOYMENT MODEL

STOX-AI runs locally on John's Kali Linux computer.

Target hardware:

- Intel Core i7-8550U;
- 12 GB RAM;
- approximately 200 GB available external-drive storage.

The source repository itself may live on the external drive.

The application must be path-independent and must not hard-code any particular Linux mount path.

Support configurable storage roots.

The normal workflow is:

```text
Turn on Kali
→ mount external drive
→ enter STOX-AI repository/environment
→ run: stox run
→ review results
→ optionally upload the generated AI-review Markdown package to an independent AI reviewer
→ shut down Kali
```

John may initially run STOX-AI mainly on weekends, but may eventually run it daily.

Therefore the same `stox run` command must work correctly whether the previous successful run was:

- yesterday;
- one week ago;
- one month ago;
- several weeks ago.

The system must automatically determine what data is missing and catch itself up incrementally.

No 24/7 runtime is required.

Do **not** build mandatory:

- cloud VM deployment;
- systemd production daemons;
- continuous schedulers;
- hourly polling;
- continuous market monitoring;
- email notification systems;
- SMS notification systems;
- SMTP/Brevo integration;
- paid AI API integration;
- recurring automated backups.

---

# 4. CORE USER EXPERIENCE

The normal command must be:

```bash
stox run
```

John should not need to remember a collection of scripts.

`stox run` must orchestrate the entire normal workflow.

Also provide simple commands such as:

```bash
stox report
stox status
stox doctor
stox holdings
```

Advanced/debug commands may exist for maintenance, development, forced training, provider validation, etc., but routine operation should center on `stox run`.

Provide a clean console script entry point through the Python package configuration.

---

# 5. WHAT `stox run` MUST DO

A normal run must perform the following process automatically and safely:

1. Load configuration.
2. Verify local state/database schema.
3. Verify required provider configuration is present.
4. Determine the last successful ingestion checkpoints.
5. Determine the latest fully completed U.S. regular-market session.
6. Fetch all missing market data.
7. Fetch all missing corporate actions.
8. Fetch all available missed historical news.
9. Fetch/update relevant SEC filings and fundamentals.
10. Refresh appropriate macroeconomic data.
11. Use optional Alpha Vantage enrichment only when useful and within its configured budget.
12. Deduplicate and validate all newly ingested data.
13. Apply corporate-action logic correctly.
14. Run data-quality and point-in-time integrity checks.
15. Determine whether any previously issued forecasts now have official entry prices available.
16. Settle any previously issued forecast horizons that have matured.
17. Update prospective forecasting statistics.
18. Rebuild only affected incremental features where practical.
19. Determine whether production models require retraining.
20. If retraining is due, train challenger models.
21. Walk-forward validate and calibrate challengers.
22. Promote a challenger only if it credibly improves upon the current champion.
23. Otherwise retain the existing champion.
24. Generate fresh 20D / 30D / 60D / 90D forecasts for the eligible universe.
25. Compute downside/risk estimates.
26. Apply data-quality, liquidity and opportunity qualification rules.
27. Re-evaluate John's manually entered holdings.
28. Produce the Primary 30D leaderboard.
29. Produce the Best Across All Horizons leaderboard.
30. Produce Top-3/high-conviction summaries.
31. Generate terminal, HTML, JSON, Markdown and AI-review Markdown reports.
32. Persist the new official predictions immutably.
33. Persist all run metadata, model versions and provider provenance.
34. Print a concise successful completion summary.

A partial failed data update must **not** advance an ingestion checkpoint as though the update succeeded.

All ingestion must be resumable and idempotent.

Running `stox run` twice must not create duplicate records.

---

# 6. INVESTMENT UNIVERSE

Eligible recommendations:

- U.S.-listed common stocks;
- normal U.S.-listed ETFs.

Do not preferentially rank a stock over an ETF or vice versa.

If an ETF has the best validated probability/return profile, it may rank first.

Exclude by default:

- OTC securities;
- securities below $5 USD;
- leveraged ETFs;
- inverse ETFs;
- warrants;
- rights;
- units;
- preferred shares;
- obviously unsuitable non-standard securities;
- securities with insufficient data;
- securities failing liquidity/data-quality requirements.

Small-cap stocks are allowed when sufficient liquidity and data quality exist.

Liquidity filters must be suitable for a contemplated trade potentially as large as approximately **$100,000 USD**.

Use robust dollar-volume and liquidity rules rather than only share volume.

Make thresholds configurable.

Do not optimize the system toward penny stocks or highly speculative microcaps.

---

# 7. FORECAST HORIZONS

Production horizons are exactly:

- **20 calendar days**
- **30 calendar days — PRIMARY**
- **60 calendar days**
- **90 calendar days**

The architecture must make horizons configuration-driven so 45D, 75D, or other horizons can be added later without redesigning the system.

However:

**Do not activate 45D or 75D in the initial production system.**

Each active horizon must have a genuine trained/validated forecast implementation.

Do not display fake extrapolations from another horizon.

---

# 8. FORECAST TIMING AND OFFICIAL PAPER ENTRY

Forecast integrity is critical.

Market-price features must use the latest **fully completed regular U.S. market session**.

News, filings and other event information may use data that became available up to the actual STOX-AI run timestamp.

Every report must display explicit cutoffs such as:

```text
Market data through: Friday close
News/filings through: Saturday 10:17 ET
Forecast issued: Saturday 10:22 ET
```

## Official prospective paper entry

An official forecast is issued at the run timestamp.

Its official paper-entry session is the **next regular U.S. market session open after forecast issuance**.

Example:

```text
Forecast generated Saturday
→ official paper entry = Monday regular-session open
```

Do not use Friday's close as the official entry price for a forecast that had access to weekend information.

If the next-session open has not occurred yet, store the forecast with a pending official entry price.

At a subsequent `stox run`, obtain and permanently record the actual next-session open once available.

## Horizon target date

The horizon clock begins from the official paper-entry date.

For a 30D forecast:

```text
target date = entry date + 30 calendar days
```

If that calendar date is not a regular trading day, settle at the **first regular U.S. market close on or after the target date**.

Apply the same rule to 20D, 60D and 90D.

Use a proper U.S. exchange calendar including holidays and early closes.

---

# 9. RETURN DEFINITION

Use **total return**, not only raw price appreciation.

Realized and modeled returns should account for:

```text
price change
+ applicable cash distributions/dividends
- configurable execution/trading friction
```

Keep trading-friction assumptions modest, explicit and configurable.

Do not pretend execution has zero friction.

Do not mix CAD/USD FX forecasting into STOX-AI.

The forecasting universe and return calculations are in **USD**.

---

# 10. PRIMARY FORECASTING OBJECTIVE

The most important quantity is:

> **Validated and calibrated probability of achieving a positive net total return.**

Probability of gain is the primary ranking criterion.

Expected return is important but secondary.

Example:

```text
Stock A:
P(gain) = 94%
Expected return = +2%

Stock B:
P(gain) = 88%
Expected return = +8%
```

Stock A normally ranks ahead of Stock B because the calibrated win probability is higher.

However, when probabilities are effectively equivalent within the resolution supported by calibration uncertainty, expected return becomes the deciding factor.

Example:

```text
20D:
P(gain) = 99%
Expected return = +1.4%

60D:
P(gain) = 99%
Expected return = +5.0%
```

The 60D opportunity should rank higher in the cross-horizon leaderboard, while the 20D opportunity should still be visible.

Do not pretend probabilities are precise to meaningless hundredths of a percentage point.

Implement sensible probability equivalence/tolerance based on calibration precision and validation sample size.

Avoid opaque arbitrary weighted scores when a transparent lexicographic ranking can be used.

---

# 11. PREFERRED RETURN TARGETS

Use the following as **soft opportunity-quality targets**, not absolute exclusion rules:

| Horizon | Preferred expected net return |
|---|---:|
| 20D | >= 1.5% |
| 30D | >= 2.0% |
| 60D | >= 4.0% |
| 90D | >= 6.0% |

An exceptionally high-confidence forecast slightly below a preferred return target may still appear.

Label such cases clearly, e.g.:

`High Confidence / Lower Return`

The system must never suppress an unusually strong calibrated forecast solely because it misses a soft return target by a small amount.

---

# 12. QUALIFYING OPPORTUNITIES

Do not force a Top 20.

A valid output may contain:

```text
2 qualifying opportunities
```

or:

```text
No sufficiently strong opportunity this run
```

instead of filling a leaderboard with weak picks.

Determine production probability/quality thresholds from proper validation rather than inventing an arbitrary confidence cutoff.

Require adequate:

- calibration;
- sample support;
- data quality;
- liquidity;
- downside profile;
- model validity.

Only qualifying names become official prospective recommendation forecasts used in the primary prospective performance statistics.

The report may optionally show a separate research/watch section for interesting but non-qualifying candidates.

Clearly separate these from official predictions.

---

# 13. TWO REQUIRED LEADERBOARDS

## Leaderboard A — Primary 30D

Rank qualifying opportunities using the **30D production forecast**.

This is the main one-month opportunity list.

Show at least:

- rank;
- ticker;
- company/fund name;
- calibrated P(gain);
- expected net return;
- median expected return;
- major downside probabilities;
- model agreement;
- data-quality/reliability status;
- earnings/event warning;
- all other active horizon forecasts.

## Leaderboard B — Best Across All Horizons

Compare the strongest opportunity/horizon combinations across:

- 20D;
- 30D;
- 60D;
- 90D.

Example:

```text
#1 XYZ 60D 96% +6.1%
#2 ABC 30D 95% +3.4%
#3 DEF 90D 94% +11.0%
#4 GHI 20D 94% +2.2%
```

Each candidate must still display its forecasts for all four horizons.

A strong longer-horizon opportunity must be allowed to outrank a shorter-horizon opportunity when calibrated probability is comparable and expected return is materially better.

---

# 14. TOP 3 / HIGH-CONVICTION PRESENTATION

The report should prominently identify:

```text
PRIMARY OPPORTUNITY
#1

ALTERNATIVE HIGH-CONVICTION PICKS
#2
#3
```

John may choose one or several positions manually.

STOX-AI must not recommend how much capital to allocate to each.

---

# 15. DOWNSIDE AND DISTRIBUTION INFORMATION

Do not report only:

```text
P(gain)
Expected return
```

For shortlisted candidates, provide as much validated distribution information as the modeling approach can reliably support, such as:

- P(return > 0%);
- P(return > +2%);
- P(return > +5%);
- expected return;
- median expected return;
- P(loss > 5%);
- P(loss > 10%);
- P(loss > 20%);
- downside/tail estimate;
- forecast interval/quantiles where validated;
- realized/historical volatility;
- drawdown context;
- event/gap-risk indicators.

Do not assume returns are normally distributed unless that assumption has been validated.

Prefer calibrated threshold models, quantile models, empirical residual approaches, or other properly validated techniques.

A high win probability with catastrophic tail risk must be visible to the user.

---

# 16. DATA PROVIDERS

The required provider philosophy is:

> **Normal operation should require $0 recurring provider cost.**

Configured local secrets may include:

```text
ALPACA_API_KEY
ALPACA_API_SECRET
FRED_API_KEY
ALPHAVANTAGE_API_KEY
SEC_USER_AGENT
```

Do not require an SMTP secret.

Do not require an AI-provider secret.

Never commit actual secrets.

Ensure `.secrets/`, `.env`, credential files and similar sensitive files are Git-ignored.

Provide safe example configuration only.

---

# 17. ALPACA — CORE MARKET PROVIDER

Alpaca Basic is the required market-data provider.

The locally tested capabilities include:

- U.S. stock/ETF historical data;
- historical SIP daily bars for completed/non-restricted periods;
- IEX access;
- historical news;
- corporate actions.

Use Alpaca for:

- tradable asset/universe metadata where appropriate;
- daily OHLCV market history;
- completed historical SIP daily bars;
- corporate actions;
- historical news;
- required reference prices where appropriate.

## SIP handling

For completed historical daily bars, prefer SIP.

Do not issue historical SIP queries whose requested end time improperly overlaps the provider's restricted recent-data window.

Determine the latest safe fully completed session/end timestamp first.

Do not rely on real-time SIP.

The medium-term forecasting system does not require real-time SIP.

## News

Alpaca historical news is Benzinga-sourced in the tested feed.

Store and preserve:

- provider news ID;
- created_at;
- updated_at;
- source;
- author;
- headline;
- summary;
- symbols;
- URL;
- ingestion timestamp.

Track updates/revisions rather than silently replacing the historical first-seen version.

Implement pagination using `next_page_token`.

When STOX-AI has been offline, fetch all missing pages until the gap is fully covered.

Deduplicate by stable provider ID.

Do not require scraping linked news websites.

Use provider-delivered headline/summary/content fields according to availability.

## Corporate actions

Ingest and correctly handle available actions including relevant:

- cash dividends;
- splits;
- symbol changes;
- mergers;
- spin-offs;
- other material adjustments when provided.

Corporate-action processing must support correct features, labels and realized total-return calculations.

---

# 18. SEC EDGAR

Use SEC EDGAR as an important company-fundamental and filing source.

Use a compliant descriptive User-Agent from:

`SEC_USER_AGENT`

Follow SEC automated-access guidance conservatively.

Use caching and rate limiting.

Stay well below aggressive request rates.

Prefer bulk/download-efficient SEC data where practical.

Use SEC data for relevant:

- 10-K;
- 10-Q;
- 8-K;
- filing metadata;
- accepted/available timestamps;
- XBRL/company facts;
- balance-sheet data;
- income-statement data;
- cash-flow data;
- material filing events.

Point-in-time integrity is mandatory.

A filing or fundamental value must never be used before it was actually publicly available.

Preserve relevant acceptance/availability timestamps.

Do not silently substitute revised values into earlier historical feature states.

---

# 19. FRED / ALFRED

Use FRED/ALFRED as supporting macro/regime data.

Potential feature families include:

- Treasury rates;
- yield curve;
- inflation;
- unemployment/labor;
- credit conditions;
- liquidity;
- economic activity;
- volatility/regime variables where available.

Prefer point-in-time/vintage-aware macro data where practical.

A later macro revision must not masquerade as information known historically.

FRED features should only remain in production models when they provide real out-of-sample value.

The forecasting engine must survive temporary FRED failure when sufficient core market data remains available.

---

# 20. ALPHA VANTAGE

Alpha Vantage is **optional enrichment**, not a core dependency.

Use it selectively for high-value data such as, where appropriate and available:

- earnings calendar;
- earnings history;
- earnings estimates;
- listing/delisting status;
- selected fundamentals/events.

Maintain a persisted configurable API-call budget.

Do not burn limited calls downloading ordinary daily stock prices that Alpaca already provides.

Alpha Vantage failure, quota exhaustion, or temporary unavailability must not prevent the core forecasting engine from operating.

If Alpha Vantage enrichment does not measurably improve out-of-sample model performance, keep it disabled in production features.

---

# 21. FEATURE ENGINEERING

Candidate feature families should include, where properly available point-in-time:

## Price/technical

- trailing returns;
- momentum;
- moving-average relationships;
- trend;
- gaps;
- realized volatility;
- downside volatility;
- drawdown;
- beta;
- relative strength;
- market-relative performance;
- sector-relative performance where possible;
- volume;
- dollar volume;
- abnormal volume;
- liquidity;
- price/volume interaction;
- recent regime shifts.

## Cross-sectional

- percentile/rank features across the current point-in-time eligible universe;
- market-relative ranks;
- peer/industry/SIC-relative ranks where valid.

## Fundamentals

Potential point-in-time variables such as:

- revenue growth;
- earnings growth;
- margins;
- free cash flow;
- operating cash flow;
- leverage;
- debt;
- liquidity;
- share-count change;
- valuation-related measures where reliable;
- capital efficiency;
- fundamental trend/change.

## Events/news

Potential features such as:

- news frequency;
- novelty;
- company relevance;
- catalyst categories;
- positive/negative event indicators;
- filing/event recency;
- earnings proximity;
- material corporate events.

Local NLP approaches may be tested if they fit the hardware and licensing requirements.

Do not require a paid language-model API.

Cache expensive local text processing.

## Macro/regime

Potential features such as:

- rate regime;
- yield curve;
- inflation regime;
- growth/labor regime;
- market benchmark regime;
- volatility regime.

## Event risk

Explicitly model or flag:

- upcoming earnings;
- recent earnings;
- major SEC filings;
- dividends;
- corporate actions;
- other known material events.

Do not automatically exclude a company because earnings occur inside the forecast horizon.

Instead:

- flag the upcoming event prominently;
- model event effects where evidence supports it;
- expose the increased uncertainty/risk.

## Feature selection

More features do not automatically imply better predictions.

Implement feature-family ablation/importance testing.

Examples:

```text
price + volume baseline
+ fundamentals
+ macro
+ news/events
+ optional enrichment
```

Retain feature families in champion models only when they improve credible out-of-sample results or otherwise satisfy a justified modeling need.

Avoid feature bloat.

---

# 22. MODELING STRATEGY

Build horizon-specific production models for:

- 20D;
- 30D;
- 60D;
- 90D.

The core statistical problem includes:

1. probability of positive total return;
2. expected/median total return;
3. downside/tail estimates.

Test multiple sensible candidate models rather than hard-coding one algorithm.

Candidate approaches may include:

- logistic/probabilistic baselines;
- gradient boosted trees;
- histogram gradient boosting;
- ExtraTrees;
- RandomForest where appropriate;
- XGBoost;
- LightGBM;
- calibrated classifiers;
- quantile/regression models;
- carefully justified ensembles.

Use models that fit the 12 GB RAM local machine.

Do not introduce deep learning simply because it sounds sophisticated.

A simpler model that performs better in real validation should win.

---

# 23. MODEL COMMITTEE / AGREEMENT

Where multiple validated models are retained as candidates or ensemble members, calculate and expose model agreement/disagreement.

Example:

```text
LightGBM       89%
XGBoost        91%
ExtraTrees     84%
Logistic       78%
```

The final displayed calibrated production probability must come from the actual champion/ensemble methodology, not from arbitrary averaging.

Expose whether model agreement is:

- high;
- moderate;
- low;

using a transparent validated rule.

Strong disagreement should be visible as uncertainty.

---

# 24. CALIBRATION

Calibration is critical.

A raw model output such as:

```text
99.3%
```

must not automatically be presented as a 99.3% real-world probability.

Use proper out-of-sample calibration.

Potential methods include:

- isotonic;
- Platt/sigmoid;
- other justified calibration approaches.

Calibration itself must avoid time leakage.

Evaluate probability reliability using:

- Brier score;
- calibration curves;
- calibration error;
- reliability buckets;
- sample counts.

For a candidate report, provide relevant historical support such as:

```text
Displayed calibrated probability: 88%

Comparable historical validation predictions:
137

Observed win rate in comparable bucket:
86.9%
```

Do not claim precision that the sample size cannot support.

---

# 25. TIME-SERIES VALIDATION AND LEAKAGE PREVENTION

This is non-negotiable.

Do not use random train/test splits that leak future information into the past.

Use proper time-aware:

- walk-forward validation;
- expanding/rolling training windows where appropriate;
- untouched holdout periods;
- purging;
- embargo around overlapping forward-return labels where necessary.

Prevent look-ahead in:

- prices;
- fundamentals;
- filings;
- news;
- macro data;
- universe membership;
- corporate actions;
- analyst/earnings data;
- revisions.

Implement automated leakage tests.

Store timestamps/provenance required to prove what information was available when a feature was created.

---

# 26. SURVIVORSHIP AND SECURITY MASTER

Maintain as much point-in-time security/universe information as reasonably possible.

Use available:

- Alpaca asset information;
- Alpha Vantage listing/delisting information where valuable;
- SEC mappings;
- symbol-history/corporate-action information.

Avoid training solely on today's surviving securities.

Handle, where possible:

- delistings;
- ticker changes;
- mergers;
- symbol changes.

If perfect historical universe reconstruction is impossible using the free sources, document the limitation explicitly and implement the strongest practical approximation.

Do not hide this limitation.

---

# 27. DATA PROVENANCE

For appropriate records preserve fields such as:

- provider;
- provider record ID;
- source event time;
- published/available time;
- provider updated time;
- ingested_at;
- first_seen_at;
- revised_at;
- effective date;
- symbol/entity identifiers.

Never overwrite an original historical observation in a way that destroys knowledge of when it first became available.

Maintain first-seen/revision history where material.

---

# 28. DATA-QUALITY GATING

Before generating forecasts, validate:

- latest expected completed session exists;
- data coverage is adequate;
- symbols are mapped correctly;
- no obvious duplicate/corrupt records;
- required price history is complete;
- corporate-action handling is coherent;
- feature generation completed;
- champion model is available;
- critical databases are healthy.

If required core market data is stale/incomplete and retries cannot repair it:

```text
FORECASTING BLOCKED
```

Do not fabricate new forecasts.

Report the exact reason.

If an optional enrichment source fails:

```text
DEGRADED MODE
```

may be acceptable.

Record exactly what was unavailable.

Optional source failure must never silently masquerade as a complete run.

---

# 29. RETRAINING

Do not blindly retrain every time `stox run` executes.

Implement a champion/challenger model registry.

Retraining may be triggered by sensible conditions such as:

- model age;
- sufficient number of newly matured labels;
- configured evaluation interval;
- material data/regime update;
- explicit forced retraining.

When training challengers:

1. rebuild the valid point-in-time training dataset;
2. train candidate models;
3. perform walk-forward evaluation;
4. calibrate properly;
5. compare against the existing champion;
6. promote only with credible improvement;
7. otherwise keep the current champion.

Persist model metadata and metrics.

Maintain a small rollback history of production champions.

Do not accumulate unlimited old model artifacts.

---

# 30. MODEL-SELECTION PRIORITIES

Primary goals are:

1. truthful calibration;
2. high hit rate among the strongest selections;
3. robust Top-1/Top-3 performance;
4. positive realized returns;
5. downside control;
6. stability across time/regimes.

Do not choose models primarily because of:

- in-sample fit;
- raw ROC AUC alone;
- one lucky backtest;
- complexity.

For the primary 30D horizon, prioritize metrics that directly reflect John's use case.

---

# 31. PERFORMANCE METRICS

Track at minimum:

- hit/win rate;
- Top-1 hit rate;
- Top-3 hit rate;
- precision among highest-ranked recommendations;
- Brier score;
- calibration error;
- calibration/reliability buckets;
- expected vs realized return;
- median realized return;
- return MAE where relevant;
- ranking quality;
- downside outcomes;
- worst realized loss;
- maximum drawdown of hypothetical evaluation strategies;
- sample size;
- benchmark-relative performance.

Use SPY and QQQ as broad-market benchmarks/context.

John's primary objective remains **absolute profit**, not merely outperforming a benchmark.

However, report benchmark-relative results so the user can determine whether STOX-AI is actually adding value.

---

# 32. BACKTEST VS PROSPECTIVE RESULTS

Keep these conceptually and physically distinct.

## Backtest

Historical simulation used for research/model development.

## Prospective

Predictions STOX-AI genuinely issued before their outcomes were known.

Prospective results become the most important evidence as the live history grows.

Never merge retrospective predictions into the prospective database in a way that makes them appear truly live.

Reports must clearly label:

- backtest statistics;
- prospective statistics.

---

# 33. IMMUTABLE OFFICIAL PREDICTIONS

Every official forecast must be permanently stored and never rewritten after issuance.

Store at least:

- unique prediction ID;
- ticker/security ID;
- forecast issue timestamp;
- information cutoff timestamps;
- latest completed market session;
- planned official entry session;
- eventual official entry price;
- 20D probability/return/risk outputs;
- 30D probability/return/risk outputs;
- 60D probability/return/risk outputs;
- 90D probability/return/risk outputs;
- target settlement dates;
- model/champion ID;
- calibration version;
- feature version;
- dataset version;
- universe version;
- provider provenance;
- qualification status;
- rank at issuance.

Each horizon settles independently.

Never delete official prospective prediction/outcome history as part of routine retention cleanup.

The storage cost of this history is tiny relative to its value.

---

# 34. HOLDINGS

Holdings are manually entered.

Do not connect to a brokerage.

Provide a simple CLI experience such as:

```bash
stox holdings add AAPL
```

Prompt for or accept:

- ticker;
- purchase date;
- purchase price;
- shares — optional.

Provide:

```bash
stox holdings list
stox holdings remove ...
```

When shares are provided, calculate actual dollar P/L as well as percentage P/L.

If a holding corresponds to a STOX-AI official forecast near the purchase time, link it where possible.

Otherwise mark it as a manually entered holding without a linked original prediction.

Every `stox run` must re-evaluate all holdings.

Show:

- original linked outlook when available;
- current 20D forecast;
- current 30D forecast;
- current 60D forecast;
- current 90D forecast;
- current expected returns;
- actual P/L;
- material news;
- upcoming earnings/events;
- important filing changes;
- model-confidence change;
- deterioration from original thesis.

Use descriptive statuses such as:

```text
HEALTHY
DETERIORATING
WARNING
MATERIAL NEGATIVE CHANGE
EXIT REVIEW
```

Do not automatically sell anything.

`EXIT REVIEW` means the evidence has deteriorated materially and deserves John's attention.

The application only evaluates holdings when run; it is not a continuous monitoring service.

---

# 35. REPORTS

Every successful run must generate:

1. concise terminal output;
2. polished local HTML report;
3. JSON machine-readable report;
4. human-readable Markdown report;
5. dedicated self-contained AI-review Markdown package.

Prefer timestamped immutable report copies plus easy-to-find latest aliases, e.g.:

```text
reports/
  runs/
    <timestamp>/
      report.html
      report.json
      report.md
      ai_review.md

  latest.html
  latest.json
  latest.md
  latest_ai_review.md
```

Generated reports should not be committed to Git.

---

# 36. MAIN REPORT CONTENT

The main report should contain sections such as:

## Run/data status

- STOX-AI version;
- Git commit;
- model versions;
- data version;
- forecast issue time;
- market-data cutoff;
- news cutoff;
- filing cutoff;
- provider health;
- degraded-mode warnings.

## Primary Opportunity

Show #1 30D opportunity prominently.

## Primary 30D Leaderboard

Up to 20 qualifying opportunities.

## Best Across All Horizons

Rank strongest horizon/candidate combinations.

## Top 3 High-Conviction Opportunities

Present #1/#2/#3 clearly.

## Candidate detail

For important candidates show:

- all four horizons;
- calibrated probability;
- expected net return;
- median return;
- downside probabilities;
- model agreement;
- preferred-return-target status;
- liquidity;
- relevant fundamentals;
- technical/relative-strength context;
- catalysts/news;
- filing context;
- upcoming earnings;
- macro/sector context;
- historical calibration support;
- known risks.

## Holdings

Only when holdings exist.

## Prediction performance

Show both:

- backtest performance;
- prospective performance.

## Data/model health

Expose limitations and degraded features.

---

# 37. AI-REVIEW MARKDOWN PACKAGE

Generate:

`reports/latest_ai_review.md`

This file is a first-class product artifact.

It must be completely self-contained.

John should be able to upload this file to an independent AI reviewer **without typing additional instructions**.

The file itself must begin with a complete instruction section.

Use language similar to:

---

# STOX-AI INDEPENDENT REVIEW PACKAGE

## Instructions for the independent AI reviewer

Review this file as an independent second-opinion analyst.

The quantitative forecasts below were produced by STOX-AI using point-in-time market, fundamental, macro, filing, news and model data.

Do not invent or replace STOX-AI's probabilities.

Do not assume that a high-ranked prediction is correct merely because STOX-AI ranks it highly.

Actively search for contradictory evidence and reasons the forecast may fail.

For each highlighted candidate:

1. summarize why STOX-AI ranks it highly;
2. identify evidence supporting the forecast;
3. identify evidence contradicting it;
4. identify upcoming earnings, filings, macro events, catalysts or company-specific events that could materially affect the outcome;
5. evaluate whether the forecast is supported across independent feature families or depends heavily on one narrow signal;
6. identify the strongest plausible failure scenario;
7. identify model disagreement, data-quality concerns, regime changes, unusual volatility, liquidity concerns or other warning signs;
8. compare the strongest candidates with each other;
9. review held positions STOX-AI has flagged as deteriorating;
10. identify anything deserving additional investigation before capital is risked.

For each highlighted candidate assign exactly one commentary label:

- SUPPORTIVE
- MIXED
- CAUTION

These labels are commentary only.

Do not recalculate STOX-AI's quantitative probabilities.

Do not alter STOX-AI's leaderboard rankings.

If access to current external information is available, independently check whether material information became public after STOX-AI's stated cutoff.

Clearly separate:

- evidence contained in the STOX-AI package;
- information independently discovered after the cutoff.

Prioritize primary sources, official company disclosures, regulatory filings and reliable financial reporting.

If newer information materially changes the risk picture, make it prominent.

Return:

1. Executive assessment
2. Review of Primary 30D #1
3. Review of Top 3 Primary 30D candidates
4. Review of strongest Across-All-Horizons candidates
5. Comparison of strongest alternatives
6. Holdings warnings, if present
7. Major risks and catalysts
8. New information discovered after STOX-AI's cutoff, if available
9. Key unresolved questions/uncertainties
10. Final evidence-review label for each candidate: SUPPORTIVE / MIXED / CAUTION

The purpose is critical review and evidence, not automatic trade execution.

---

Following those instructions, embed the actual STOX-AI evidence package.

For detailed review, include:

- Primary 30D Top 3;
- strongest Across-All-Horizons candidates;
- unique candidates among these;
- any holding with meaningful deterioration/warning status.

Do not dump the entire market into the AI package.

Include a compact Top-20 table for wider context.

For detailed candidates include enough information for a meaningful review:

- all four forecasts;
- expected returns;
- downside estimates;
- model agreement;
- calibration/sample statistics;
- important feature contributions/explanations;
- fundamentals;
- recent relevant news summaries;
- SEC filing summaries;
- earnings date/event proximity;
- corporate actions;
- macro/sector context;
- historical comparable-signal performance;
- known risks;
- data cutoffs;
- model/data versions.

Do not require a paid AI API inside STOX-AI.

The AI review package is an export artifact only.

---

# 38. EXPLAINABILITY

Provide useful model explanations without pretending causal certainty.

For tree models, SHAP or comparable explanations may be used if computationally practical.

For candidate reports, surface the strongest feature contributions in understandable language.

Distinguish:

```text
model-associated feature contribution
```

from:

```text
proven economic cause
```

Do not tell John that a feature "caused" the prediction unless that conclusion is actually justified.

---

# 39. LOCAL DATA ARCHITECTURE

Prefer a simple local stack.

Recommended architecture:

## SQLite

Use for transactional/smaller structured state such as:

- configuration metadata;
- ingestion state/checkpoints;
- security master;
- holdings;
- predictions;
- outcomes;
- model registry;
- run registry;
- provider state;
- data-quality status.

## Partitioned Parquet

Use for large analytical datasets such as:

- historical bars;
- news/event normalized data where appropriate;
- fundamentals snapshots;
- feature matrices;
- training datasets.

## DuckDB

Use for:

- analytical queries;
- feature/backtest access;
- large Parquet scans;
- evaluation/reporting.

Avoid unnecessary infrastructure such as:

- PostgreSQL;
- Redis;
- Kafka;
- Kubernetes;
- Elasticsearch;

unless there is an overwhelming technical reason.

The application should remain portable and easy for one person to operate.

---

# 40. STORAGE MANAGEMENT

Available external storage is approximately 200 GB.

Design normal operation to remain **well below 100 GB** where practical.

Provide a configurable hard/soft storage budget; approximately 150 GB may be treated as a sensible upper safety boundary by default.

Use:

- incremental ingestion;
- Parquet compression;
- partition pruning;
- deduplication;
- compaction when useful;
- bounded temporary files;
- bounded logs;
- bounded old model artifacts;
- cleanup of interrupted downloads;
- cleanup of obsolete feature caches that can safely be rebuilt.

Do **not** routinely delete:

- official prospective predictions;
- settled prediction outcomes;
- essential model provenance;
- critical audit metadata.

Do not create automatic recurring backup ZIPs or database copies.

No scheduled automatic application backups are required.

---

# 41. GIT AND SECRETS

GitHub stores source code and documentation.

Do not commit:

- API keys;
- `.secrets/`;
- `.env`;
- downloaded market data;
- databases;
- Parquet warehouses;
- model artifacts;
- generated reports;
- logs;
- temporary files.

Create a robust `.gitignore`.

Provide safe example configuration files with blank/example values only.

The project must work regardless of the external drive's mount path.

---

# 42. PYTHON / PACKAGING

Use Python as the primary implementation language.

Prefer modern packaging through:

`pyproject.toml`

Provide reproducible dependency installation.

Target a reasonable modern Python version compatible with Kali and the selected ML libraries.

Avoid unnecessary dependency bloat.

Provide:

- console entry point for `stox`;
- clear bootstrap/setup script;
- version reporting;
- migration/schema handling.

---

# 43. INITIAL BOOTSTRAP

Provide a one-command or very simple first-time bootstrap experience.

A command such as:

```bash
stox bootstrap
```

may perform the initial historical setup.

It must be resumable.

Initial bootstrap should:

1. validate environment;
2. initialize schemas/directories;
3. build the security universe;
4. download available historical daily market data;
5. retrieve/calculate corporate actions;
6. ingest appropriate historical SEC/fundamental data;
7. retrieve macro history/vintages;
8. obtain optional enrichment within budget;
9. build historical point-in-time datasets;
10. create 20D/30D/60D/90D labels;
11. train candidate models;
12. walk-forward validate;
13. calibrate;
14. select champions;
15. create model registry;
16. run self-tests;
17. produce initial evaluation reports.

Bootstrap must not require constant manual babysitting.

If interrupted, it should resume safely.

---

# 44. LABELING

For each historical candidate date/security/horizon, calculate forward **net total return** according to the same conceptual rules used prospectively.

Historical labels must account correctly for:

- entry timing;
- horizon settlement date;
- dividends/distributions;
- corporate actions;
- trading-calendar logic;
- configurable friction.

Do not accidentally use adjusted-price data in a way that double-counts dividends or corporate actions.

Document the exact labeling formula.

---

# 45. TESTING

Automated tests must consume **zero live provider calls by default**.

Use:

- fixtures;
- mocks;
- synthetic datasets;
- sanitized provider response examples;
- deterministic seeds.

Test at minimum:

## Core

- config loading;
- schema creation/migration;
- CLI;
- storage paths;
- security filters;
- holdings commands.

## Providers

- Alpaca parsing;
- SIP safe-cutoff logic;
- pagination;
- news deduplication/revision;
- corporate actions;
- SEC parsing/throttling logic;
- FRED/ALFRED parsing;
- Alpha Vantage budgeting;
- retry/backoff;
- partial failure handling;
- checkpoints.

## Data integrity

- duplicate prevention;
- timestamps;
- missing sessions;
- stale-data detection;
- corporate-action adjustment;
- point-in-time availability;
- historical universe handling where implemented.

## Modeling

- label generation;
- walk-forward splits;
- purge/embargo;
- no-lookahead tests;
- deterministic features;
- deterministic backtests where expected;
- model training;
- calibration;
- ranking;
- probability equivalence/tie behavior;
- qualification rules;
- downside modeling.

## Predictions

- immutable forecast issuance;
- pending paper entry;
- official next-open assignment;
- independent horizon settlement;
- dividend-inclusive realized return;
- prospective/backtest separation.

## Reports

- terminal output;
- HTML;
- JSON;
- Markdown;
- AI-review Markdown;
- holdings deterioration output.

## Recovery

- interrupted ingestion;
- duplicate rerun;
- stale optional provider;
- stale core provider;
- disk-threshold behavior.

Run the automated test suite before declaring the build complete.

Fix failures and rerun.

---

# 46. LIVE PREFLIGHT

Because real credentials must remain local to John, include a command such as:

```bash
stox doctor --live
```

or an equivalent explicit live provider-validation command.

It should safely test, without excessive API usage:

- Alpaca authentication;
- Alpaca daily historical data;
- Alpaca news;
- Alpaca corporate actions;
- FRED;
- SEC;
- Alpha Vantage if configured.

Do not expose secret values.

Print clear PASS/WARN/FAIL results.

Optional-provider failures should be distinguished from core-provider failures.

---

# 47. HEALTH / STATUS

Provide:

```bash
stox status
```

showing useful information such as:

- application version;
- Git commit;
- schema version;
- last successful run;
- last completed market session;
- latest market data;
- news checkpoint;
- filing checkpoint;
- macro checkpoint;
- current production models;
- model training dates;
- number of prospective predictions;
- pending/matured outcomes;
- disk usage;
- provider health;
- degraded-mode status.

Make this understandable to a non-developer.

---

# 48. DOCUMENTATION

Create a professional README/operator manual containing:

- what STOX-AI does;
- system requirements;
- installation;
- local external-drive operation;
- virtual environment/setup;
- secrets setup;
- provider configuration;
- bootstrap;
- normal `stox run` workflow;
- report interpretation;
- two leaderboards;
- holdings;
- status/doctor;
- retraining behavior;
- model evaluation;
- prospective vs backtest results;
- storage behavior;
- troubleshooting;
- upgrade/migration workflow;
- Git workflow;
- data/provider limitations.

Also provide documentation such as:

- `ARCHITECTURE.md`
- `DATA_PROVENANCE.md`
- `MODEL_CARD.md` or model documentation
- `CHANGELOG.md`
- safe secrets/config example.

Document limitations honestly.

---

# 49. SOURCE CODE QUALITY

Use clear modular boundaries such as:

- configuration;
- providers;
- ingestion;
- security master;
- storage;
- feature engineering;
- labels;
- models;
- calibration;
- validation/backtesting;
- ranking;
- holdings;
- predictions/outcomes;
- reporting;
- CLI.

Use typing where useful.

Use structured logging.

Avoid giant monolithic scripts.

Do not over-engineer.

Optimize for:

- correctness;
- auditability;
- local usability;
- reproducibility;
- maintainability.

---

# 50. FAILURE BEHAVIOR

Core rule:

> STOX-AI must prefer no forecast over a misleading forecast.

If core price data cannot be trusted:

- block new predictions;
- preserve last trustworthy results;
- explain the failure.

If an optional source fails:

- continue where justified;
- mark degraded mode;
- record missing feature families.

A failed AI-review export must never invalidate numerical predictions.

A failed optional enrichment source must never destroy the main run.

---

# 51. WHAT SUCCESS MEANS

The long-term success criteria are:

1. **How accurate were STOX-AI's probabilities?**
2. **How often did the highest-ranked picks actually make money?**
3. **How much money did the hypothetical Top-1 and Top-3 strategies make?**
4. **How severe were the losses when predictions were wrong?**
5. **Did the system add value relative to straightforward benchmarks?**

Emphasize genuine prospective performance over time.

Do not optimize merely for impressive historical backtests.

---

# 52. ACCEPTANCE CRITERIA

Do not consider the project complete until all feasible items below are satisfied.

## Build

- clean Python package;
- reproducible setup;
- console `stox` command;
- Git-safe secret handling;
- schemas/migrations;
- local storage layout.

## Data

- provider adapters implemented;
- incremental checkpointed ingestion;
- safe SIP daily-bar handling;
- news pagination;
- corporate actions;
- SEC;
- FRED/ALFRED;
- optional Alpha Vantage budget;
- point-in-time timestamps/provenance.

## ML

- active 20D/30D/60D/90D models;
- time-aware validation;
- leakage protections;
- calibration;
- expected-return modeling;
- downside estimates;
- champion/challenger registry;
- model agreement where appropriate.

## Decisions

- qualification logic;
- no-forced-pick behavior;
- Primary 30D leaderboard;
- Across-All-Horizons leaderboard;
- Top-3 section;
- earnings/event warnings;
- holdings deterioration logic.

## Prospective tracking

- immutable forecasts;
- next-session-open paper entry;
- independent horizon settlement;
- total-return outcomes;
- prospective metrics separate from backtests.

## Reports

- terminal;
- HTML;
- JSON;
- Markdown;
- self-contained AI-review Markdown.

## Operations

- `stox bootstrap`;
- `stox run`;
- `stox report`;
- `stox status`;
- `stox doctor`;
- holdings workflow;
- resumable recovery.

## Testing

- offline automated tests;
- end-to-end fixture run;
- leakage tests;
- deterministic evaluation where appropriate;
- no default live API consumption.

---

# 53. END-TO-END OFFLINE DEMONSTRATION

Before finishing, run an offline/synthetic or fixture-based end-to-end workflow that proves the architecture can:

1. ingest representative data;
2. build features;
3. create 20D/30D/60D/90D labels;
4. train/test models;
5. calibrate probabilities;
6. generate forecasts;
7. rank opportunities;
8. create both leaderboards;
9. create a holding and detect a changed outlook;
10. issue an immutable forecast;
11. settle a synthetic matured outcome;
12. generate every report format including `latest_ai_review.md`.

Do not claim real provider/live-market validation unless actual live credentials were available.

Instead provide John with the exact local `stox doctor --live` and bootstrap steps required after pulling the repository.

---

# 54. GITHUB DELIVERY

Work in the connected repository:

`whylikethat/stox-ai`

Use disciplined Git commits.

Do not commit secrets, data, models or generated reports.

Prefer a clean build branch during implementation.

After the implementation and tests pass:

- push the completed source;
- leave the repository in a clean usable state;
- if repository permissions/workflow allow safe merge to the intended main branch, complete it;
- otherwise clearly tell John the exact branch and commit containing the completed build.

Report:

- branch;
- final commit hash;
- tests run;
- test results;
- anything requiring John's local live-provider validation.

---

# 55. FINAL USER HANDOFF

In the final Work response, address John by name.

Give John a concise operational handoff covering:

1. what was built;
2. repository branch/commit;
3. how to pull it;
4. how to create/use the Python environment;
5. where `.secrets/providers.env` belongs;
6. exact expected variable names;
7. how to run the live provider doctor;
8. how to run the one-time bootstrap;
9. how to run `stox run`;
10. where the reports are located;
11. how to manage holdings;
12. how to interpret the two leaderboards;
13. any limitations that remain.

Do not overwhelm John with internal implementation trivia.

The intended routine after setup should be essentially:

```bash
stox run
```

followed by reviewing the two leaderboards and supporting evidence.

---

# 56. FINAL ENGINEERING PRINCIPLE

STOX-AI must be built around this principle:

> **Accuracy, calibration, data integrity and honest prospective evidence matter more than complexity, impressive-looking probabilities, feature count, model sophistication, or the number of recommendations produced.**

If the evidence is weak, say so.

If no opportunity qualifies, say so.

If a simpler model wins, use it.

If an optional dataset does not improve real validation, do not force it into production.

If a forecast says 95%, STOX-AI should have empirical evidence that predictions assigned approximately that level of confidence deserve it.

The system should continuously accumulate evidence about whether its own predictions are actually trustworthy.

Build the complete project accordingly.