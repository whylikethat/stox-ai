# Model card

**Purpose:** medium-term U.S. common-stock/ordinary-ETF research. **Excluded uses:** execution, position sizing, shorting, options, tax classification and guaranteed-profit claims. **Initial horizons:** 20/30/60/90 calendar days. Each horizon trains separately; no extrapolated horizon outputs.

## Estimators and target

Target: net total return from the next session's raw open to the calendar-defined settlement close, with verified distributions/splits and configured friction. Candidate algorithms are regularized logistic/Ridge and histogram gradient boosting. Threshold classifiers model returns exceeding -20%, -10%, -5%, 0%, +2%, +5%. Separate sigmoid calibration and monotone probability projection produce coherent exceedance probabilities. Mean-return and 10th/50th/90th quantile regressions accompany probabilities. The holdout reports actual 80%-interval coverage; no normality assumption is imposed.

An alternative candidate produces disagreement information, not an unvalidated average of probabilities. Local perturbation explanations compare each input with its training reference median. Correlated-feature dependence limits these explanations; they are model-associated changes, not causal effects.

## Temporal evaluation

Sorted dates split the most recent 20% into final holdout. On the earlier development segment, expanding training windows predict subsequent fold periods. Training labels must end at least five calendar days before validation starts. The last quarter of each training segment is calibration data, itself purged from base-model fitting. Model/family selection uses development-fold Brier loss and calibration error. Optional-family improvement must exceed 0.005 versus the best baseline; this is a documented engineering selection margin, not proof that the family is economically causal.

The final model is not refit on the holdout. This deliberately trades some freshness for uncontaminated calibration evidence. Automatic retraining is due after both a configured age and newly matured-label count; forced retraining still requires promotion evidence. Candidate/champion comparison is restricted to dates after both models' calibration periods plus embargo. A positive 95% lower bound on paired block-mean Brier improvement and nonworsening calibration is required to replace an existing champion.

## Qualification and uncertainty

A qualification probability threshold is learned from development reliability buckets whose lower block-adjusted confidence bound exceeds 50%. Final holdout calibration must be acceptable, Brier no worse than the holdout base rate, and independent-block support sufficient. Each forecast must have a supported comparable bucket, positive expected return, accepted liquidity/history/source health and catastrophic-loss estimate within the configured risk ceiling. No threshold means no official recommendation.

Reliability intervals use conservative horizon-plus-five-day blocks rather than treating every overlapping stock/date label as independent. This is still an approximation: serial regimes and cross-sectional dependence may extend beyond a block. Eight blocks is a minimum gate, not a claim of precise tail estimation. Displayed probabilities must be read together with counts, bucket intervals and calibration errors. Extreme-loss estimates can be weakly supported even when gain calibration is good.

Ranking uses probability first, then expected return within the smaller of the compared candidates' reported probability resolutions. Groups anchor to the highest remaining probability to avoid nontransitive pairwise sorting. Risk controls are transparent policy limits; they are not claimed to be financially optimal thresholds.

## Reported evidence

Brier, calibration error and buckets; overall and Top-1/Top-3 hit rates; mean/median/worst returns; return MAE; expected versus realized mean; return-rank correlation; nonoverlapping Top-1/Top-3 compounded-return/drawdown summaries; interval coverage; threshold Brier losses; sample/block counts; SPY/QQQ excess returns. Prospective metrics are computed only from previously issued qualified forecast/horizon outcomes, stored separately from backtests.

## Known limitations

No live market training, entitlement validation, full-universe throughput measurement or real prospective performance is included in this source release. Synthetic data are useful only for software verification. Incomplete historical security membership, backfilled corrections, event coverage, daily open/close reference conventions, survivorship, sampled cross-sectional context, stale training windows and unmodeled corporate transformations limit inference. Complex-action quarantines may preferentially exclude adverse events and bias apparent historical performance; this limitation must be considered explicitly.

A model can remain a research champion without qualifying recommendations. Never lower evidence gates merely to make the product emit picks. Retain the simpler model if stronger methods do not improve credible evidence.
