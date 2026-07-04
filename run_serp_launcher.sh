#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer the project venv: the GUI launches child scripts with the same
# interpreter (sys.executable), so running the venv python here is what
# gives run_pipeline.py etc. access to the installed dependencies.
if [[ -x "$SCRIPT_DIR/venv/bin/python3" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
else
  PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Error: no venv at $SCRIPT_DIR/venv and no Python at $PYTHON_BIN" >&2
    echo "Create the venv first: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
    exit 1
  fi
  echo "Warning: venv not found — running with $PYTHON_BIN; pipeline scripts may lack dependencies." >&2
fi

exec "$PYTHON_BIN" serp-me.py
