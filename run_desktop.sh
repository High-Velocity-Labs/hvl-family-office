#!/usr/bin/env bash
# run_desktop.sh - Run local desktop app
# Usage: ./run_desktop.sh [--reset-vault] [--no-browser] [--browser] [--port 5050]

set -euo pipefail
cd "$(dirname "$0")"

# Activate venv if present
if [[ -f ".venv/bin/activate" ]]; then
    source ".venv/bin/activate"
elif [[ -f "venv/bin/activate" ]]; then
    source "venv/bin/activate"
fi

python3 desktop_app.py "$@"
