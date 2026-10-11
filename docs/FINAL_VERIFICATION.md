# STOX 2.3 verification — 2026-10-11

## Scope and result

This release adds forward challenger evaluation, bounded earnings history, causal sector affinity and additional SEC fundamentals, licensed local signal imports, and model/data audit reporting. It does not establish a profitable strategy. Existing champions and strict qualification gates remain active.

Four frozen challengers were evaluated against the existing historical dataset in an isolated runtime copy. The resource cap for this one-time evaluation was 40,000 eligible training rows per horizon; the new default cap for subsequent challenger evaluations is 60,000. Holdout results were not used to tune this release after inspection.

| Horizon | Selected development family / algorithm | Holdout rows | Independent blocks | Brier | Base Brier | Calibration error | Validated |
|---|---|---:|---:|---:|---:|---:|---|
| 20D | price + market / logistic | 7,655 | 29 | 0.25209 | 0.24814 | 0.07158 | No |
| 30D | price + market / logistic | 7,596 | 21 | 0.25456 | 0.24614 | 0.09227 | No |
| 60D | price / histogram boosting | 7,458 | 11 | 0.25339 | 0.23903 | 0.12931 | No |
| 90D | price / histogram boosting | 7,351 | 8 | 0.26643 | 0.23356 | 0.18728 | No |

Lower Brier is better. These challengers did not outperform the constant-probability baseline on the untouched holdout. No accuracy improvement or validated recommendation is claimed. Their probability/median conflict diagnostic was zero, but consistency alone is not predictive skill. Additional feature families were either not selected in development or lacked sufficient point-in-time development coverage. Forward paired trials collect independent new evidence; they do not waive historical qualification failures.

## Verification coverage

The offline suite covers synthetic four-horizon training, interruption/resume, repeat-run idempotency, research persistence/settlement, qualified separation, inconsistent forecasts, screening, history expansion, local status, identifier/CUSIP protection and all report formats. New tests cover earnings first observation, SEC accession matching, causal sector proxies, unsupported-symbol refresh starvation, optional feed failure rotation, licensed import validation/expiry, schema preservation, frozen paired forecasts/entry prices, single evaluation, rejection, zero-settlement expiry and per-horizon prospective ranks.

Live doctor passed Alpaca assets, historical SIP, news and corporate actions; SEC; FRED; and Alpha Vantage. A bounded earnings-history pass received 286 quarterly records across three common stocks without a failed symbol. This is delayed observed information, not a reconstructed historical vintage.

## Data preservation and operation

Source installation backed up replaced files. Before schema 4 -> 5, a consistent SQLite backup was taken under the existing runtime writer lock. The migration adds trial tables and immutable-record triggers; it does not erase history, forecasts, outcomes, holdings, watchlist or provider checkpoints. Only frozen challenger artifacts and evaluation metadata are transferred from verification; test forecasts, outcomes, prices and provider records are not transferred.

User config, secrets, local production-config changes and pre-existing untracked files are excluded from the commit. Normal operation remains `stox run`; no bootstrap, reset, paid subscription or repeated forced retraining is required. New default limits are three earnings symbols per run and 60,000 training rows per challenger, within the existing Alpha daily request budget. See [FINAL_PRODUCT.md](FINAL_PRODUCT.md) for source availability, terms and remaining limitations.

Independent evidence can take many months; the default 90D forward trial can exceed two years. A lack of validated opportunities remains a valid output. More feeds and more elapsed time do not guarantee improvement.

## Installed-runtime checks

* Two sequential isolated live runs each emitted 3,524 current research rows across 20D/30D/60D/90D, zero newly duplicated forecast snapshots, and zero qualified opportunities. Probability/return/qualification values were identical on unchanged inputs. All four trials held 854 paired symbol predictions each after the second run.
* The repeat-run report retained 1,217 contradictory legacy-model forecasts as visibly flagged research, rather than changing their underlying values or qualifying them.
* Installed schema is 5. Comparing all pre-migration forecast/entry/outcome/holding rows against the SQLite backup found zero missing or changed rows (881 original forecast snapshots; no settled outcomes yet).
* `stox status` returned successfully in 0.107 seconds while the production writer was active.
* Existing unresolved corporate-action notices remain visible; affected histories/outcomes can remain excluded. The release does not fabricate resolutions.

## Complete offline suite

Final source: `python -m pytest -q -o addopts=''` — **184 passed in 753.70 seconds (12m33s)**. No tests were deselected in this final run. `git diff --check` and module compilation also passed. Earlier focused and broad runs were supplementary; the final complete result above includes the late SEC refresh and zero-settlement-expiry regressions.

## Final production run

The installed external-drive application completed successfully (exit 0), run `2026-10-11T175445.528512_0000-7870f5ed`. It produced 3,524 research rows across all four horizons, zero qualified opportunities, zero duplicate/new research snapshots on unchanged model/price inputs, and four collecting forward trials with 854 paired forecasts each. HTML was 39,174 bytes. News, SEC, FRED, Alpha and earnings-history health were PASS; public disclosures reported OK. The compatible-model path skipped historical label rebuilding and completed its model stage in 8.9 seconds. Optional refreshes and feature-cache rebuilding still consume time; no fixed runtime promise is made.

Production report: `.stox/reports/runs/2026-10-11T175445.528512_0000-7870f5ed/report.html`. Source and database backup: `.stox-local/final-backup-20261011T175311Z/`. The retained SQLite file is `state-before-schema5.sqlite`.
