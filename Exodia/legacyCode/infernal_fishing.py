"""
DEPRECATED — use InfernalEelFishing instead.

Run:
  cd Exodia && python -m InfernalEelFishing.infernal_eel_fishing
  ./InfernalEelFishing/run_infernal_eel.sh

This legacy script had inverted action gating, stack-blind inventory counting,
and incorrect spot-click strategy. Do not use for production runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

if __name__ == "__main__":
    print(__doc__, file=sys.stderr)
    print("Launching InfernalEelFishing.infernal_eel_fishing ...", file=sys.stderr)
    from InfernalEelFishing.infernal_eel_fishing import (
        _ensure_images_cwd,
        _parse_args,
        _run_infernal_eel_session,
    )
    from InfernalEelFishing.infernal_eel_log import close_run_logger, install_run_logger

    _ensure_images_cwd()
    args = _parse_args()
    install_run_logger(Path(args.log_file) if args.log_file else None)
    try:
        _run_infernal_eel_session(args)
    finally:
        close_run_logger()
