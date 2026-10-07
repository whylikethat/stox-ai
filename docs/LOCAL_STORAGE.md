# Local installation and storage (2.0.4)

With the repository on an external drive and the default configuration, STOX's
dependencies, data, installer downloads and temporary files stay on that drive.
They are ignored by Git; committing runtime data is not required for this behavior.

| Purpose | Default location relative to repository |
| --- | --- |
| Python environment and installed dependencies | `.venv/` |
| pip download/wheel cache | `.stox-local/pip-cache/` |
| pip build, uninstall/rollback and installer temporary files | `.stox-local/tmp/` |
| Installer XDG cache | `.stox-local/cache/` |
| Database, warehouse, models, reports and application logs | `.stox/` |
| Python/SQLite temporary files | `.stox/tmp/` |
| joblib temporary arrays | `.stox/tmp/joblib/` |
| Runtime XDG cache and application caches | `.stox/cache/` |

The OS Python interpreter and its standard library remain a system prerequisite;
the venv can reference that interpreter. Operating-system logs, swap and caches of
other applications are controlled by the OS/other applications. STOX does not move
or delete pre-existing home caches. This change cannot attribute earlier disk growth.

## Configuration and existing data

An editable installation now selects `config.toml` beside its source checkout even
when launched from another directory. This prevents accidentally creating `.stox`
under the caller's current directory. A non-editable wheel without a checkout retains
the current-directory fallback. Explicit `--config` / `STOX_CONFIG` and `--root` /
`STOX_HOME` overrides are preserved; relative roots resolve beside the chosen config.
If you previously intentionally used a different config, pass `--config` explicitly.
No existing root is moved, renamed or deleted. An explicitly configured root outside
the repository is reported by setup and `paths`; it is not silently redirected.

Runtime scratch settings take effect before the CLI loads providers/models and are
also applied around direct `engine.run()` calls. The process-scoped context restores
its environment on exit. Do not concurrently run different roots in one Python process.
The configured scratch directories may not symlink outside their data root. Setup
similarly refuses a `.venv` or installer scratch directory pointing outside the repo.

`status`, `paths` and report reading do not create scratch directories or open a
writable store. Deep diagnostics still open SQLite read-only; any temporary sorting
files they need are kept under the runtime root, so the CLI may create scratch folders.

## Setup and upgrade

From the existing repository, with STOX stopped and storage functioning reliably:

```bash
git pull --ff-only
bash scripts/setup.sh
```

Wait for `Setup complete`. Setup does not launch bootstrap or open the runtime
database. It prints its paths, tests a small scratch file with write/fsync/rename/read,
uses an existing supported Python 3.11–3.13 venv, installs locked dependencies and
the editable package, runs `pip check`, and verifies installed/source versions agree.
It preserves existing config, credentials and runtime state. An unreadable or
unsupported venv is left in place with an error instead of being recreated.
On a fresh installation, `STOX_PYTHON=/path/to/python3.13 bash scripts/setup.sh`
can select the interpreter. Setup never automatically upgrades the OS Python.

Check paths before continuing:

```bash
.venv/bin/python -m stox paths
```

With default configuration, `data_inside_repository` should be `true`, and all
printed data/cache/temp paths should point at this checkout. Keep any original
explicit config/root overrides when running these commands.

For an existing pre-repair database, run:

```bash
.venv/bin/python -m stox upgrade
.venv/bin/python -m stox diagnose --deep --integrity
```

After successful upgrade/diagnostics (integrity result `ok`), resume:

```bash
.venv/bin/python -m stox bootstrap
```

The schema-3 page checkpoints and legacy backfill retain the guarantees and
limitations documented in [bootstrap recovery](BOOTSTRAP_REPAIR.md), including
the verification replay required when old code never saved provider page cursors.

`bash scripts/setup.sh --check` only checks interpreter/path/I/O preflight and prints
locations. It can create installer scratch directories and its temporary probe; it
does not install packages or open SQLite. A passed small probe is not a disk-health
certificate.

## Input/output errors

`Errno 5: Input/output error` accompanied by kernel `Medium Error` / `Unrecovered read
error` messages is a storage problem. Changing cache paths cannot repair unreadable
sectors. Preserve/recover existing runtime files onto reliable storage before further
installation or bootstrap writes. Neither setup nor upgrade performs filesystem
repair, automatic VACUUM, database deletion or a clean bootstrap.

The command sequence uses separate steps so an installation failure is visible
before upgrade/bootstrap. There is no promise of a working live run while the
underlying drive reports read/write failures or provider access is unverified.
