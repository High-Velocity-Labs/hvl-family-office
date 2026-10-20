#!/usr/bin/env bash
# run_local.sh - Run local Flask development server
# Usage: ./run_local.sh [--reset-vault] [--port 5050]

set -euo pipefail
cd "$(dirname "$0")"

PORT="5050"

# Parse optional arguments
for arg in "$@"; do
    case "$arg" in
        --reset-vault)
            echo "[HVL Family Office] Resetting local vault directory..."
            python3 -c "from desktop_app import get_default_local_data_dir, reset_local_vault; reset_local_vault(get_default_local_data_dir())"
            ;;
        --port=*)
            PORT="${arg#*=}"
            ;;
        *)
            ;;
    esac
done

# Activate venv if present
if [[ -f ".venv/bin/activate" ]]; then
    source ".venv/bin/activate"
elif [[ -f "venv/bin/activate" ]]; then
    source "venv/bin/activate"
fi

export LOCAL_MODE=1
export FAMILY_OFFICE_PORT="$PORT"
python3 -m flask run --port "$PORT"
