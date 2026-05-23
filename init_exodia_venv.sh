#!/usr/bin/env bash
# Bootstrap a Botting-local venv without python3-venv / ensurepip (Debian PEP 668).
# Usage: bash init_exodia_venv.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VEN="${ROOT}/.venv"
PY="${VEN}/bin/python3"

if [[ ! -x "${PY}" ]]; then
  python3 -m venv --without-pip "${VEN}"
fi
curl -fsSL https://bootstrap.pypa.io/get-pip.py | "${PY}"
"${VEN}/bin/pip" install -U pip setuptools wheel
# Py 3.12 wheels (avoid broken pins in requirements-linux.txt on 3.12+)
"${VEN}/bin/pip" install \
  "numpy>=1.26" \
  "opencv-python-headless>=4.8" \
  "mss>=9" \
  "Pillow>=10" \
  "pytesseract>=0.3.10" \
  "PyAutoGUI>=0.9.54" \
  "scipy>=1.11" \
  "scikit-learn>=1.3"
echo "OK: ${VEN} ready. WSL/WSLg: if screenshots are black with mss, try:"
echo "  EXODIA_CAPTURE_BACKEND=wsl_ps cd ${ROOT}/Exodia && ${VEN}/bin/python3 capture_runelite_once.py --full-primary"
echo "  (Writes under Exodia/captures/, wiped each run; use -o for a different primary path.)"
