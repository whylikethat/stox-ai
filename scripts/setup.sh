#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
stox_repo=$(pwd -P)
stox_phase='preflight'
trap 'printf "STOX setup failed during %s. Do not start bootstrap until setup succeeds. If the error is Input/output error, preserve the drive data before retrying.\n" "$stox_phase" >&2' ERR
if [[ $# -gt 1 || (${1:-} != '' && ${1:-} != '--check') ]]; then
  printf '%s\n' 'Usage: bash scripts/setup.sh [--check]' >&2
  exit 2
fi

# Set these before venv/ensurepip/pip runs. Never use the home cache or /tmp.
export TMPDIR="$stox_repo/.stox-local/tmp"
export TMP="$TMPDIR" TEMP="$TMPDIR"
export PIP_CACHE_DIR="$stox_repo/.stox-local/pip-cache"
export XDG_CACHE_HOME="$stox_repo/.stox-local/cache"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PIP_CONFIG_FILE=/dev/null PIP_USER=false
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1
unset PIP_TARGET PIP_PREFIX PIP_ROOT PYTHONPATH PYTHONHOME

# An existing supported venv wins, even when Kali's system python3 is now 3.14.
stox_python=''
if [[ -e .venv || -L .venv ]]; then
  if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -B -c 'import sys; from pathlib import Path; raise SystemExit(not ((3,11) <= sys.version_info[:2] < (3,14) and sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() == Path(".venv").resolve()))'; then
    printf '%s\n' 'Existing .venv is unreadable, invalid or uses unsupported Python. It has been preserved. STOX requires a local Python 3.11–3.13 venv; do not delete .stox.' >&2
    exit 1
  fi
  stox_python="$stox_repo/.venv/bin/python"
else
  for candidate in "${STOX_PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    [[ -n "$candidate" ]] || continue
    if command -v -- "$candidate" >/dev/null 2>&1 && "$candidate" -B -c 'import sys; raise SystemExit(not ((3,11) <= sys.version_info[:2] < (3,14)))'; then
      stox_python=$(command -v -- "$candidate")
      break
    fi
  done
  if [[ -z "$stox_python" ]]; then
    printf '%s\n' 'Python 3.11–3.13 is required. Install a supported interpreter, or set STOX_PYTHON to its path. No runtime database was opened.' >&2
    exit 1
  fi
fi
"$stox_python" -B scripts/check_setup.py
if [[ ${1:-} == '--check' ]]; then exit 0; fi

stox_phase='virtual environment'
if [[ ! -e .venv ]]; then "$stox_python" -B -m venv .venv; fi
stox_phase='dependencies'
.venv/bin/python -m pip install -r requirements.lock
stox_phase='package installation'
# The lock installs setuptools/wheel; no second isolated build environment is needed.
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
stox_phase='installation verification'
.venv/bin/python -m pip check
.venv/bin/python -B scripts/check_setup.py --installed
if [[ ! -f config.toml ]]; then cp config.example.toml config.toml; fi
mkdir -p .secrets
chmod 700 .secrets
if [[ ! -f .secrets/providers.env ]]; then
  cp providers.env.example .secrets/providers.env
  chmod 600 .secrets/providers.env
fi
printf '%s\n' 'Setup complete. Activate: source .venv/bin/activate' 'Check locations: .venv/bin/python -m stox paths' 'Existing data: .venv/bin/python -m stox upgrade'
