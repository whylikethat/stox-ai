# 2.1.0 release verification

Base: `cf28022668783e9888042ab88b46e71d380cc0aa` (2.0.5). Version: 2.1.0.

- Supported Python 3.13 clean environment: `bash scripts/setup.sh` completed, locked dependencies installed, `pip check` passed.
- Full offline suite: **143 tests passed**. Tests block network connections.
- Standalone synthetic acceptance: 2016-01-01 through 2026-10-09, eight symbols, four trained horizons, 32 research forecasts. Repeated identical run created zero new symbol snapshots. All detected conflicting outputs were unqualified. Synthetic outcomes were absent from live prospective metrics.
- Schema upgrade on the acceptance warehouse passed and retained existing bars, events and checkpoints. Regression tests cover legacy schemas and immutable forecast preservation.
- Local doctor: database integrity, storage and all dependencies passed.
- Local metadata-only status: success, measured 0.0071 seconds on the acceptance warehouse. This is a local measurement, not a latency guarantee at every scale.
- Syntax compilation and whitespace checks passed.
- Live doctor was attempted and failed explicitly because this workspace has no Alpaca API key/secret. No live-market bootstrap, user-drive migration or successful real `stox run` is claimed. Run the documented live checks on the existing installation.

The release retains the observed limitation that Alpaca asset metadata does not
reliably supply capitalization. Known micro-caps are excluded; unknown-cap stocks
are filtered by price and liquidity but cannot be certified non-micro-cap. Optional
SEC enrichment is bounded and does not make this guarantee. This limitation is
visible in the modeling-universe metadata and run warnings.

Coverage includes interruption/resume of feeds, price prefixes, screening batches and
atomic forecast issuance; duplicate reruns and A/B/A snapshots; cross-symbol dedup;
research/qualified settlement cohorts; QCOM/MU-style inconsistencies; two-stage
screening and selected-only history; CUSIP/provider-ID namespace regression;
optional-provider degradation; reports; local status; storage limits and compaction.

## Changed files

- `.gitignore`
- `CHANGELOG.md`
- `README.md`
- `config.example.toml`
- `config.production.toml`
- `docs/PRODUCTION_UPGRADE.md`
- `docs/RELEASE_VERIFICATION.md`
- `pyproject.toml`
- `src/stox/__init__.py`
- `src/stox/cli.py`
- `src/stox/config.py`
- `src/stox/demo.py`
- `src/stox/diagnostics.py`
- `src/stox/engine.py`
- `src/stox/features.py`
- `src/stox/ingestion.py`
- `src/stox/models.py`
- `src/stox/predictions.py`
- `src/stox/ranking.py`
- `src/stox/reporting.py`
- `src/stox/screening.py`
- `src/stox/security.py`
- `src/stox/storage.py`
- `src/stox/streams.py`
- `src/stox/universe.py`
- `tests/conftest.py`
- `tests/test_integrity.py`
- `tests/test_product.py`
- `tests/test_starter.py`
