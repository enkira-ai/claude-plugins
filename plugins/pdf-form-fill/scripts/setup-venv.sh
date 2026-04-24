#!/usr/bin/env bash
# Set up a shared Python virtual environment for the pdf-form-fill plugin.
# Idempotent — safe to run multiple times.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR ..." >&2
    python3 -m venv "$VENV_DIR"
fi

if [ -f "$REQUIREMENTS" ]; then
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
fi

echo "Setup complete. venv ready at $VENV_DIR" >&2
