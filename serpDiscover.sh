#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: Python 3.12 not found at $PYTHON_BIN" >&2
  echo "Install Python 3.12 from python.org, or update PYTHON_BIN in this script." >&2
  exit 1
fi

source venv/bin/activate
exec "$PYTHON_BIN" serp-me.py
