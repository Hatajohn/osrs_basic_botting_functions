#!/usr/bin/env python3
"""
Calibrate RuneLite client window rect for WSL + Windows RuneLite.

Captures the Windows primary monitor, lets you drag a box around the RuneLite
window, and saves ``client_rect.json`` (Win32 screen coordinates).

Usage:
  cd Exodia && source exodia/bin/activate
  python calibrate_client_rect.py

Manual (no GUI — e.g. headless SSH):
  python calibrate_client_rect.py --rect 100,200,765,503

Then run the bot (rect loads automatically):
  python -m SacredEelFishing.sacred_eel_fishing
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_EXODIA = Path(__file__).resolve().parent


def _ensure_wsl_ps() -> None:
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file() and not os.environ.get("EXODIA_CAPTURE_BACKEND"):
        os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
        os.environ["EXODIA_INPUT_BACKEND"] = "wsl_ps"


def _parse_rect(raw: str) -> list:
    parts = [int(x.strip()) for x in raw.replace(" ", "").split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError("Rect must be LEFT,TOP,WIDTH,HEIGHT with positive width/height")
    return parts


def _finish(rect: list, note: str) -> int:
    from bot_client_config import save_client_rect

    cfg = save_client_rect(rect, note=note)
    print("")
    print("Saved client rect:", rect, "->", cfg)
    print("")
    print("Run the bot (loads client_rect.json automatically):")
    print("  python -m SacredEelFishing.sacred_eel_fishing")
    print("")
    print("Or one-shot without saving:")
    print("  python -m SacredEelFishing.sacred_eel_fishing --rect %d,%d,%d,%d" % tuple(rect))
    return 0


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Calibrate RuneLite client window rect")
    p.add_argument(
        "--rect",
        metavar="L,T,W,H",
        help="Save rect without GUI (Win32 screen coordinates)",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    _ensure_wsl_ps()
    args = _parse_args(argv)

    if args.rect:
        try:
            rect = _parse_rect(args.rect)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return _finish(rect, note="calibrate_client_rect.py --rect")

    try:
        import cv2
        import bot_env as Env
        from roi_picker import select_roi_bgr
    except ImportError as exc:
        print("Missing dependency:", exc, file=sys.stderr)
        print("  source exodia/bin/activate && pip install -r requirements-minimal.txt")
        return 1

    print("Capture backend:", Env.capture_backend_label())
    print("Grabbing primary monitor — drag a box around the RuneLite client window.")

    img = Env.screen_image(rect=None)
    if img is None or img.size == 0 or float(img.mean()) < 1.0:
        print("Capture looks blank. Try: export EXODIA_CAPTURE_BACKEND=wsl_ps", file=sys.stderr)
        return 1

    out_png = _EXODIA / "captures" / "calibrate_primary.png"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), img)
    print("Saved reference screenshot:", out_png)

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("", file=sys.stderr)
        print("ERROR: python3-tk is required for the ROI picker.", file=sys.stderr)
        print("  sudo apt-get install -y python3-tk", file=sys.stderr)
        print("Or enter coords manually:", file=sys.stderr)
        print("  python calibrate_client_rect.py --rect LEFT,TOP,WIDTH,HEIGHT", file=sys.stderr)
        return 1

    if not os.environ.get("DISPLAY"):
        os.environ.setdefault("DISPLAY", ":0")

    print("Opening ROI picker (tkinter)...")
    try:
        roi = select_roi_bgr(img, title="Select RuneLite window")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print("")
        print("Open the screenshot and measure the client window, then run:")
        print("  python calibrate_client_rect.py --rect LEFT,TOP,WIDTH,HEIGHT")
        print("Screenshot:", out_png)
        return 1

    if roi is None:
        print("Calibration cancelled.")
        return 1

    x, y, w, h = roi
    if w <= 0 or h <= 0:
        print("Calibration cancelled (empty selection).")
        return 1

    pl, pt, _, _ = Env.primary_monitor_rect()
    rect = [x + pl, y + pt, w, h]
    return _finish(rect, note="calibrate_client_rect.py")


if __name__ == "__main__":
    raise SystemExit(main())
