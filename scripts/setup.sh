#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
if [[ ! -f config.toml ]]; then cp config.example.toml config.toml; fi
mkdir -p .secrets
chmod 700 .secrets
if [[ ! -f .secrets/providers.env ]]; then
  cp providers.env.example .secrets/providers.env
  chmod 600 .secrets/providers.env
fi
printf '%s\n' 'Setup complete. Activate: source .venv/bin/activate' 'Edit .secrets/providers.env locally, then: stox doctor --live'
