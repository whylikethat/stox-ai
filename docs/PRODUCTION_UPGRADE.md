# STOX-AI 2.1 production upgrade

Research forecasts are ranked independently of qualification. Every modeled security
has 20/30/60/90 calendar-day forecasts. Top 20 30D, Top 20 across horizons and Top 3
research highlights are visible even when no model passes strict validation. A rank
is not a claim of validated predictive skill. Probability estimates are unchanged;
conflicting classifier/return outputs rank after forecasts without detected conflicts
and cannot qualify. Low committee agreement also prevents qualification.

## Existing healthy installation (Kali)

Stop an existing writer with Ctrl-C, then run from your existing checkout:

```bash
cd /run/media/unknown/MAXIMAL/stox-ai
git pull --ff-only
bash scripts/setup.sh
source .venv/bin/activate
export STOX_CONFIG="$PWD/config.production.toml"
stox paths
stox upgrade
stox doctor
stox doctor --live
stox bootstrap --retrain
stox run
stox status
stox report --format html
```

`config.production.toml` is the exact core production profile: `.stox` beside the
repository config, history from 2016-01-01, four horizons, 1,000 selected liquid
securities plus mandatory benchmarks, holdings and user-managed watchlist, $5
minimum price and $20 million median daily dollar volume. Price discovery uses 90
recent calendar days, batches of 100 and at least 20 observed sessions. Long-history
expansion uses resumable windows up to 365 days. News, SEC, FRED and Alpha Vantage
are disabled in this core profile; they are optional, not requirements for forecasting.
The existing `.secrets/providers.env` remains in use. Setup preserves existing config
and secrets. The production profile does not overwrite `config.toml`.

If `stox paths` does not identify your existing healthy `.stox`, set `STOX_HOME` to
that exact existing directory **before upgrade**. Do not delete it or run bootstrap
against an unintended empty root. New installations omit `stox upgrade` (which
intentionally refuses empty state). Existing Parquet history is retained and only
missing prefixes/current bars are fetched. A supported Python 3.11–3.13 is required;
setup preserves an existing supported environment even if Kali defaults to 3.14.

Keep `STOX_CONFIG` set in subsequent shells, or pass
`stox --config /absolute/path/to/config.production.toml run`. Edit the committed
production profile in a separate local copy for persistent personal overrides.
`universe_size` can be set to 500–1500; mandatory names can take the total above the
cap. `symbols=[]` enables autonomous discovery. A nonempty `symbols` list retains
explicit restricted-universe behavior. Watchlist commands do not submit orders:

```bash
stox watchlist list
stox watchlist add AAPL
stox watchlist remove AAPL
stox holdings list
```

No watchlist entries are created by discovery. Unresolved/excluded holdings or
watchlist identifiers are reported, never sent blindly to ticker endpoints. Market
cap is checked when supplied by asset metadata; otherwise $5/strong-liquidity
screening is a proxy, not proof of non-micro-cap status. Current-universe history is
subject to survivorship bias. These limitations are not erased by a larger history.

## Optional enrichment and recurring runs

To enable sources, change their booleans in your local config and supply their
credentials/user agent. News lookback remains 90 days independently of 2016 prices;
`news_pages_per_run=100` bounds each news pass, preserving an unfinished cursor.
`sec_symbols_per_run=20` bounds company refreshes, least-recently-refreshed first.
FRED and Alpha are optional. Failures are visible and a compatible core price model
continues; an enrichment-dependent model is retrained without unavailable families.
There is no direct Benzinga integration.

A recurring `stox run` refreshes the recent screen incrementally, downloads missing
history only for newly selected names, updates prices and checkpointed/batched
corporate actions, settles due snapshots, reuses compatible models unless retraining
is due, ranks all available research forecasts, and writes HTML/Markdown/JSON.
Previously selected names with open forecasts continue getting prices for settlement.
Unqueryable/delisted securities remain unresolved, never silently scored as wins.
Repeat identical snapshots reuse persistent IDs even after intervening different
snapshots. Numerical/model/data/qualification changes create new snapshots; wall-clock
changes alone do not. Offline runs display research without issuing live forecasts.
Synthetic runs are clearly marked and excluded from live prospective statistics.

Run after the completed exchange session and the provider's SIP delay (for a normal
16:00 ET close, after 16:20 ET); weekend runs use the last completed session. A cold
installation still needs adequate core history and trained models. Missing core
prices/actions or insufficient training history cause an explicit failure rather
than fabricated forecasts. A successful run does not guarantee any validated picks.

## Expected terminal structure

Counts, ranks and numerical values depend on your downloaded data; this is a layout,
not an asserted live result:

```text
[recent-universe-screen] ... complete
[bars] ... complete
[corporate-actions] ... complete
[features] ... complete
[labels-and-settlement] ... complete
[models] ... complete
[report-export] ... complete
Completed. <N> research forecasts; <Q> validated opportunities in Top 20; <S> new symbol snapshots.
TOP 3 — 30D RESEARCH
#1 <symbol> 30D P(gain)=... expected net=... median=... loss>5/10/20%=... agreement=... consistency=... [RESEARCH]
  <exact exclusion reasons>
  session=... close=... median dollar volume=... <event context>
TOP 20 — 30D RESEARCH
...
TOP 20 — ACROSS HORIZONS
...
STRICT VALIDATED OPPORTUNITIES: none
PER-HORIZON VALIDATION
<validated flag, threshold or null, samples, blocks, Brier/base Brier, calibration error,
 supported buckets, train/calibration/holdout ranges, exact failure reasons>
Reports: .../.stox/reports/runs/...
```

## Schema and recovery

Schema 3 → 4 is additive and transactional under the writer lock. It adds
`forecast_snapshots`, `forecast_snapshot_members`, `universe_screen`, `watchlist`, and
an indexed forecast symbol/time lookup. Existing immutable forecasts, outcomes,
holdings, action identifiers, checkpoints, model artifacts and Parquet are retained.
Legacy forecasts are not retrospectively reclassified or invented. Research outcomes
start accumulating from newly issued snapshots. Existing short-history/legacy models
are rebuilt once to establish the expanded-history metadata. Model selection still
uses development walk-forward folds, temporal purging, calibration and a final
holdout; logistic and histogram gradient boosting remain the candidates. No extra
estimator or arbitrary probability averaging has been introduced without evidence.

Snapshot metadata is stored once per snapshot; catalyst context once per symbol.
Bulk prices/features/labels/screen caches use Parquet. Generated run reports retain
the newest 30 completed directories; immutable forecast/outcome history is retained.
User-added files prevent automatic report-directory deletion. Storage safety limits
remain 100GB soft / 150GB hard, with free-space safeguards. Optional manual maintenance:

```bash
stox diagnose --integrity
stox compact --vacuum
```

Stop writers before integrity/compaction. Compaction checks integrity and free space
and never deletes forecast records. `stox status` is read-only local metadata and does
not open Parquet files or contact providers. Ctrl-C returns 130 and preserves completed
batches/windows and atomic snapshots. Rerun the same bootstrap/run command to resume.
An unfinished first-history prefix resumes at its last committed window.

## Acceptance checks

```bash
bash scripts/setup.sh --check
python -m pytest
stox --root "$PWD/.stox-local/demo-acceptance" demo --end 2026-10-09
```

Use an empty isolated demo root, never your healthy live `.stox`. The offline test
suite blocks network access and covers migrations, setup, causal features, purging,
calibration, four-horizon training, fault injection, atomic rollback, settlement,
idempotency, CUSIP separation, transaction budgets, screens, reports and fast status.
A synthetic or provider-fixture pass verifies software behavior; it is not live-market
validation, nor evidence that any real model meets the qualification gates.
