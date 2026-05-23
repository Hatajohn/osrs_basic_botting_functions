#!/usr/bin/env bash
# Run sacred eel fishing with the Exodia venv (images/ resolved via cwd switch in script).
set -euo pipefail
EXODIA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$EXODIA_DIR/exodia/bin/python"
VENV_PIP="$EXODIA_DIR/exodia/bin/pip"
REQ="$EXODIA_DIR/requirements-minimal.txt"

# WSLg / Linux GUI: PyAutoGUI needs a display and a readable .Xauthority file.
export DISPLAY="${DISPLAY:-:0}"
if [[ ! -f "${HOME}/.Xauthority" ]]; then
  touch "${HOME}/.Xauthority"
fi

if [[ ! -x "$VENV_PY" ]]; then
  echo "Creating venv at Exodia/exodia ..."
  python3 -m venv "$EXODIA_DIR/exodia"
fi

"$VENV_PIP" install --upgrade pip setuptools wheel >/dev/null

if ! "$VENV_PY" -c "import cv2" 2>/dev/null; then
  echo "Installing dependencies from requirements-minimal.txt ..."
  "$VENV_PIP" install -r "$REQ"
fi

# PyAutoGUI → MouseInfo hard-requires tkinter on Linux (calls sys.exit without it).
if ! "$VENV_PY" -c "import tkinter" 2>/dev/null; then
  echo ""
  echo "ERROR: python3-tk is not installed (required for mouse control on Linux/WSL)."
  echo ""
  echo "Run once, then re-run this script:"
  echo "  sudo apt-get update"
  echo "  sudo apt-get install -y python3-tk python3-dev"
  echo ""
  exit 1
fi

# Session log (truncated each run): Exodia/logs/sacred_eel_latest.log
#   tail -f "$EXODIA_DIR/logs/sacred_eel_latest.log"

# WSL + Windows RuneLite: calibrate once if you have not yet:
#   cd Exodia && source exodia/bin/activate && python calibrate_client_rect.py
# One-shot perception check (no clicks):
#   ./SacredEelFishing/run_sacred_eel.sh diagnose
cd "$EXODIA_DIR"
exec "$VENV_PY" -m SacredEelFishing.sacred_eel_fishing "$@"
