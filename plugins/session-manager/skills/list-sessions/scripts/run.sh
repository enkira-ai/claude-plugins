#!/usr/bin/env bash
# Run list-sessions.py using the plugin's virtual environment.
# Automatically runs setup if the venv doesn't exist yet.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python3"

# Auto-setup if venv is missing
if [ ! -f "$PYTHON" ]; then
    bash "$SCRIPT_DIR/setup.sh" >&2
fi

exec "$PYTHON" "$SCRIPT_DIR/list-sessions.py" "$@"
