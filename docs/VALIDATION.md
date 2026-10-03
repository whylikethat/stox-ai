# Offline validation — 2026-10-03

Test command:

```bash
python -m pytest tests
```

Result: **27 passed in 34.99 seconds** in the tested Python 3.12 build environment. Test fixtures globally block socket connections. No live provider requests were consumed.

The suite includes configuration/path handling, redaction, calendar holidays/early closes and SIP delay, dividend/split accounting, unknown-action quarantine, revision history, persisted budgets, macro as-of revisions, purged temporal boundaries, probability ties, security/liquidity filters, immutable issuance, pending entry, independent horizon settlement, repeated issuance/outcome idempotency, prospective-only statistics, holdings, storage/schema safeguards, pagination/token-loop errors, partial ingestion failure, HTTP retry behavior, SEC/FRED parsing, calibration edge cases, CLI operations and causal feature invariance.

The end-to-end fixture test seeds eight synthetic securities, builds labels and trains/calibrates **all four horizons**, generates **all report formats**, creates/reviews a holding, issues an explicitly manufactured synthetic forecast fixture, settles all matured horizons and verifies a materially deteriorating holding. Manufactured fixture forecasts are labeled synthetic and are not asserted to have passed real recommendation qualification.

Separate command:

```bash
stox --root /tmp/stox-e2e doctor
```

Local database integrity, storage and dependency checks passed. Provider checks correctly reported that they were not contacted. A standalone synthetic CLI run also produced all latest-report aliases and trained all four horizons. Synthetic metrics are not evidence of market accuracy.

No claims are made about live entitlements, real-market training, full-universe performance on the target laptop, exchange-auction prices or prospective investment results. The operator must run `stox doctor --live`, then `stox bootstrap`, with credentials stored locally.
