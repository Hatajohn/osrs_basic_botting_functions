#!/usr/bin/env bash
# Run infernal eel fishing with the Exodia venv (images/ resolved via cwd switch in script).
set -euo pipefail
EXODIA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$EXODIA_DIR/exodia/bin/python"
VENV_PIP="$EXODIA_DIR/exodia/bin/pip"
REQ="$EXODIA_DIR/requirements-minimal.txt"

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

if ! "$VENV_PY" -c "import tkinter" 2>/dev/null; then
  echo ""
  echo "ERROR: python3-tk is not installed (required for mouse control on Linux/WSL)."
  echo "  sudo apt-get install -y python3-tk python3-dev"
  echo ""
  exit 1
fi

# Session log: Exodia/logs/infernal_eel_latest.log
# One-shot perception check (no clicks):
#   ./InfernalEelFishing/run_infernal_eel.sh diagnose
cd "$EXODIA_DIR"
exec "$VENV_PY" -m InfernalEelFishing.infernal_eel_fishing "$@"
