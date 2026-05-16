#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENVDIR="$ROOT_DIR/.venv"
if [ -d "$VENVDIR" ]; then
  echo "Virtualenv already exists at $VENVDIR"
else
  python -m venv "$VENVDIR"
fi
if [ -f "$VENVDIR/bin/activate" ]; then
  source "$VENVDIR/bin/activate"
elif [ -f "$VENVDIR/Scripts/activate" ]; then
  source "$VENVDIR/Scripts/activate"
fi
pip install --upgrade pip setuptools wheel
if [ -f "$ROOT_DIR/requirements.txt" ]; then
  pip install -r "$ROOT_DIR/requirements.txt"
fi
echo "Environment ready. To activate: source $VENVDIR/bin/activate (Linux/macOS) or $VENVDIR\\Scripts\\activate (Windows)"
