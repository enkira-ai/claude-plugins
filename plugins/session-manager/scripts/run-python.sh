#!/usr/bin/env bash
# Generic runner: executes any Python script using the plugin's shared venv.
# Usage: run-python.sh <script.py> [args...]
# Auto-creates the venv on first use.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python3"

if [ ! -f "$PYTHON" ]; then
    bash "$SCRIPT_DIR/setup-venv.sh"
fi

exec "$PYTHON" "$@"
