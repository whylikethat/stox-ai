# Fast-start forecasts (2.0.5)

Use `config.starter.toml` for a bounded first installation. It contains 110 representative
stocks and ordinary ETFs across sectors, including SPY and QQQ, price history starting
2023-01-01, all four calendar-day horizons, and all four optional sources disabled.
The exact configuration is checked in at the repository root. Unspecified settings retain
the ordinary validation, liquidity, storage, model and risk-policy defaults.
This is an operational starting point, not evidence of investment accuracy. Real forecasts
can be research-only; zero qualifying opportunities is a valid successful result.

## Fresh healthy external SSD / Kali

Run these from a terminal whose current directory is on the mounted healthy external SSD.
Use a local Linux filesystem (ext4 recommended). These instructions never format a drive.
Verify the mount with `findmnt -T .` and available space with `df -h .` first.

System prerequisites (these are the only system-wide installations):

```bash
sudo apt update
sudo apt install git python3.13 python3.13-venv
```

STOX requires Python 3.11–3.13. If your Kali repositories do not offer 3.13,
use an available supported interpreter and matching venv package (e.g. 3.12), then set
`STOX_PYTHON` to its path. Do not use Python 3.14 or install pip packages into system Python.

Clone, set up, and verify the package:

```bash
git clone --branch main https://github.com/whylikethat/stox-ai.git
cd stox-ai
bash scripts/setup.sh --check
bash scripts/setup.sh
.venv/bin/python -m stox paths
bash scripts/self-test.sh
```

Setup keeps `.venv` and installer caches/temp files in the checkout. Runtime scratch lives
under the selected data root. `.stox`, `.stox-local`, credentials and model/database artifacts
remain excluded from Git. Setup does not delete or reset an existing database.

For an existing checkout, use `git pull --ff-only`, then `bash scripts/setup.sh`.
Do not reclone over existing runtime data. There is no new database schema migration in 2.0.5;
older schema versions still use the existing non-destructive migration.

Check the example without overwriting your existing configuration, then run an isolated demo:

```bash
.venv/bin/python -m stox --config config.starter.toml --root .stox-local/starter-demo demo --end 2026-10-09
.venv/bin/python -m stox --config config.starter.toml doctor
```

The demo uses eight fixture securities from the configured universe, synthetic prices and
a longer deterministic fixture history. It must use its own empty root. The regression suite
separately exercises **2023-01-01 through 2026-10-09** with actual training of all four
horizons. Neither demo nor tests contact real providers. Do not interpret synthetic outputs
as live forecasts or move the demo database into `.stox`.

Edit `.secrets/providers.env` locally and fill in `ALPACA_API_KEY` and `ALPACA_API_SECRET`.
Other provider credentials are unnecessary for this profile. Never paste keys into Git,
a report or a support message. Then run:

```bash
.venv/bin/python -m stox --config config.starter.toml doctor --live
.venv/bin/python -m stox --config config.starter.toml bootstrap
.venv/bin/python -m stox --config config.starter.toml run
```

Use the same `--config` on every command. Alternatively, copy the starter file to your own
`config.toml` on a fresh installation and thereafter use plain `stox bootstrap` / `stox run`
with `.venv/bin` activated. Existing users should review configuration changes rather than
overwriting their current file or changing its `root` unintentionally.

The live doctor must pass the core Alpaca asset, historical SIP and corporate-action checks.
Disabled optional sources show `DISABLED` and make no network requests. A successful
network connection alone does not prove historical data entitlements; bootstrap needs the
requested historical SIP bars and corporate actions from the account.

## If fresh Kali only provides Python 3.14

Keep system Python unchanged. From the cloned repository, this optional one-time block
installs a managed Python 3.12 and its installer into `.stox-local`, then runs the existing
setup script. It needs `python3-venv` (`sudo apt install python3-venv`) and Internet access.
It does not open `.stox`, replace an existing venv, or install anything into the home cache.
The managed interpreter must remain in place because the application venv references it.

```bash
python3 - <<'PYTHON'
from pathlib import Path
import os, subprocess
repo = Path.cwd().resolve()
assert (repo / "scripts/setup.sh").is_file(), "Run inside the stox-ai checkout"
env = os.environ.copy()
for key, folder in {
    "TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp",
    "PIP_CACHE_DIR": "pip-cache", "XDG_CACHE_HOME": "cache",
    "UV_CACHE_DIR": "uv-cache", "UV_PYTHON_INSTALL_DIR": "python",
    "UV_PYTHON_CACHE_DIR": "python-downloads", "UV_PYTHON_BIN_DIR": "bin",
}.items():
    location = repo / ".stox-local" / folder
    location.mkdir(parents=True, exist_ok=True)
    env[key] = str(location)
env.update(PIP_CONFIG_FILE="/dev/null", PIP_USER="false", PYTHONNOUSERSITE="1")
for key in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PYTHONPATH", "PYTHONHOME"):
    env.pop(key, None)
def run(*args):
    return subprocess.run(args, env=env, check=True)
tools = repo / ".stox-local" / "python-installer"
run("python3", "-m", "venv", str(tools))
run(str(tools / "bin/python"), "-m", "pip", "install", "uv")
uv = str(tools / "bin/uv")
run(uv, "python", "install", "3.12")
env["STOX_PYTHON"] = subprocess.check_output(
    [uv, "python", "find", "--managed-python", "3.12"], env=env, text=True).strip()
run("bash", "scripts/setup.sh")
PYTHON
```

The uv storage controls are documented at https://docs.astral.sh/uv/reference/environment/.
This fallback is for interpreter availability; it is not a workaround for disk I/O errors.
After setup succeeds, continue with the same self-test/demo/doctor/bootstrap/run commands above.

## Expected progress and output

Stages retain elapsed time, processed/total where known, pages, inserted and skipped counts:

1. Assets and authoritative universe resolution.
2. Raw daily bars for selected securities plus required benchmarks/holdings.
3. Legacy action index (empty/quick on a fresh database), then corporate-action pages.
4. News, SEC, FRED and earnings: `disabled`, with an explicit reason.
5. Features, labels and settlement.
6. Models: 20D, 30D, 60D, 90D (walk-forward selection, calibration and holdout evaluation).
7. Ranking and reports, then report export and `Completed.`

Reports are `.stox/reports/latest.html`, `latest.md`, `latest.json` and `latest_ai_review.md`.
The JSON `research_candidates` contains forecasts for the trained horizons, including models
that have not qualified for recommendations. `official_forecast_ids` and recommendation
leaderboards may be empty without the run failing. Reports disclose switches, provider
health, selected feature columns, family labels and validation limits. No validation gates
are relaxed for fast-start. Roughly four years is enough to exercise the pipeline at the
October 2026 fixture date, but does not establish accurate probabilities or sufficient
independent holdout evidence, especially at 90D. No live-runtime ETA is claimed.

A repeat run reuses completed session bars, recent action snapshots and compatible models,
then updates new sessions/outcomes as available. It does not enable optional sources by
itself. The existing refresh overlap and durable page receipts remain in use. Repeated
identical snapshots do not issue duplicate official forecasts. Interrupt with Ctrl-C;
restart the same command/configuration to reuse durable work.

## Independent enrichment policy

- `enable_news = false`: no news calls, including live doctor. `true` requests news starting
  at current run time minus `news_lookback_days` on first use; it never uses price
  `history_start`. Subsequent runs use their checkpoint with a seven-day correction overlap,
  bounded by the configured lookback. The default is 90 days; 60 is also supported.
- News lookback changes use a separate durable job scope. An old, unbounded pre-repair news
  job cannot force the new profile back into years of news. Old rows/receipts are retained.
  Counts before observed news coverage are missing, not fabricated zeros. A short news
  history may not have enough support to enter model selection; price models remain valid.
- `enable_sec = false`: no mappings, company requests or CIK loop. Existing cached SEC
  evidence is retained but excluded from this profile's features and reports.
- `enable_fred = false`: no FRED/ALFRED requests. Set true independently for vintage-aware
  macro context. Failure is reported and does not block a compatible price model.
- `enable_alpha_vantage = false`: no earnings calls or budget consumption, even if a key
  exists. Earnings enrichment never gates core price training.

All four default to true in `config.example.toml`; full optional enrichment remains available.
News lookback remains independent even in that full profile. Unsupported/unavailable feature
families stay missing and cannot silently re-enter from cached records when disabled.
An old enrichment-dependent champion is not reused when its selected optional inputs are
absent; the existing price-model training path is used instead.

## Corporate-action contract and coverage

Alpaca documents `symbols` as a comma-separated filter for GET `/v1/corporate-actions`:
https://docs.alpaca.markets/us/reference/corporateactions-1

Restricted universes send only authoritative typed market-data tickers (including benchmarks
and holdings), never CUSIPs/ISINs/provider IDs. Full `symbols=[]` requests remain unfiltered.
Requests retain ascending, inclusive process-date windows of at most 31 days, limit 1000,
and the provider's opaque page token. Rows, identifiers, raw-payload receipts and cursor
commit atomically per page. Filters are included in the checkpoint scope; expanding the
universe cannot reuse a differently filtered cursor or mark full-market history complete.
Existing action payload receipts deduplicate replayed records. Completed full-universe
legacy checkpoints are retained.

The documented symbol filter does not guarantee that a current ticker finds every prior
name/merger/counterparty event. STOX retains its identifier/action safety checks, and reports
continue to disclose incomplete historical identity coverage and provider announcement lag.
An unsupported action can still exclude a security. For wider historical event discovery,
use full-universe mode; no unsupported provider parameters are invented.

## Expand later, using the same data root

Copy `config.starter.toml` to a private `config.toml` before editing, or keep using an explicitly
named local configuration. Keep `root = ".stox"` pointing to the same directory.

- Add symbols gradually; `symbols = []` enables the autonomous eligible universe. New symbols
  download history; existing prices are reused. Changing the action filter gets its own
  covered snapshot and deduplicates existing payloads.
- Move `history_start` earlier. Histories initially ingested by 2.0.5 record the requested
  starting date. Expansion backfills only the missing prefix in durable 31-day windows;
  subsequent retries skip completed windows. Existing bar files are merged, never deleted.
  Interrupted first downloads retain their existing partial-bar resume behavior. Legacy
  data without a recorded starting boundary retains the previous resume behavior; inspect
  its actual date coverage before assuming an earlier configuration alone extends it.
- Enable news with a bounded lookback (e.g. 60/90), then optionally SEC/FRED/Alpha with their
  credentials. SEC first use can fetch substantial company history; enable it deliberately
  after the core product works. FRED retains vintage pagination; Alpha retains its budget.
- Run with the edited config; use `run --retrain` when you explicitly want to evaluate models
  against expanded history/enrichment immediately. Ordinary runs retain the normal retrain
  schedule and champion/challenger validation rules.

Keep a separate backup of `.stox` for portability. Cloning Git restores software/configuration,
not price files, model artifacts or databases; these are intentionally not committed.
