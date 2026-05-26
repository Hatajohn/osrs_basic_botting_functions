#!/usr/bin/env python3
"""
One-shot debug frame renderer for the Exodia desktop UI.

Captures the RuneLite client window, runs inventory perception, and writes an
annotated PNG to ``captures/ui_debug_latest.png``. Prints a single JSON line to
stdout for the Electron shell to parse.

Usage:
  python exodia_debug_frame.py
  python exodia_debug_frame.py --mode inventory_identify
  python exodia_debug_frame.py --mode raw_client
  python exodia_debug_frame.py --mode inventory_grid
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

from bot_inventory_detect import (  # noqa: E402
    draw_inventory_occupancy_overlay,
    inventory_occupancy_from_client,
)
from bot_inventory_items import (  # noqa: E402
    draw_inventory_item_identify_overlay,
    identify_inventory_slot_items,
    is_frame_bucket_label,
)
from tests.inventory_test_common import capture_client_bgr, locate_inventory_rect  # noqa: E402

_OUTPUT_PATH = _EXODIA / "captures" / "ui_debug_latest.png"
_MAX_WIDTH = 640

_MODES = ("inventory_identify", "raw_client", "inventory_grid")


def _ensure_capture_env() -> None:
    os.chdir(_EXODIA)
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file() and not os.environ.get("EXODIA_CAPTURE_BACKEND"):
        os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
    os.environ.setdefault("EXODIA_INV_FRAME_BUCKETS", "1")


def _scale_to_max_width(image: np.ndarray, max_width: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w <= max_width:
        return image
    scale = max_width / float(w)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _count_slot_stats(
    occupancy: List[List[bool]],
    slot_items: Optional[List[List[Optional[str]]]],
) -> Dict[str, int]:
    occupied = sum(1 for row in occupancy for cell in row if cell)
    unknown = 0
    tmp_count = 0
    if slot_items is not None:
        for row in range(len(occupancy)):
            for col in range(len(occupancy[row])):
                if not occupancy[row][col]:
                    continue
                if row >= len(slot_items) or col >= len(slot_items[row]):
                    continue
                label = slot_items[row][col]
                if label == "?":
                    unknown += 1
                elif label is not None and is_frame_bucket_label(label):
                    tmp_count += 1
    return {"occupied": occupied, "unknown": unknown, "tmp_count": tmp_count}


def _emit(result: Dict[str, Any]) -> None:
    print(json.dumps(result, separators=(",", ":")))


def render_debug_frame(mode: str) -> Dict[str, Any]:
    if mode not in _MODES:
        return {"ok": False, "mode": mode, "error": "invalid mode: %s" % mode}

    client, err = capture_client_bgr()
    if client is None:
        return {
            "ok": False,
            "mode": mode,
            "error": err or "capture failed",
            "hint": "calibrate client rect (client_rect.json) and ensure RuneLite is visible",
        }

    if mode == "raw_client":
        overlay = _scale_to_max_width(client, _MAX_WIDTH)
        _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(_OUTPUT_PATH), overlay):
            return {"ok": False, "mode": mode, "error": "failed to write %s" % _OUTPUT_PATH}
        h, w = overlay.shape[:2]
        return {
            "ok": True,
            "mode": mode,
            "path": str(_OUTPUT_PATH),
            "width": w,
            "height": h,
        }

    inv_rect, _outline_score, _grid_score = locate_inventory_rect(client)
    if inv_rect is None:
        return {
            "ok": False,
            "mode": mode,
            "error": "inventory panel not found",
            "hint": "open inventory in RuneLite or recalibrate client_rect.json",
        }

    occ, _count, _proto = inventory_occupancy_from_client(client, inv_rect)
    if occ is None:
        return {"ok": False, "mode": mode, "error": "occupancy grid failed"}

    slot_items: Optional[List[List[Optional[str]]]] = None
    if mode == "inventory_identify":
        slot_items, _scores, _diag = identify_inventory_slot_items(
            client,
            inv_rect,
            occ,
            frame_buckets=True,
        )
        overlay = draw_inventory_item_identify_overlay(client, inv_rect, slot_items, occ)
    else:
        overlay = draw_inventory_occupancy_overlay(
            client, inv_rect, occ, draw_panel_outline=True
        )

    overlay = _scale_to_max_width(overlay, _MAX_WIDTH)
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(_OUTPUT_PATH), overlay):
        return {"ok": False, "mode": mode, "error": "failed to write %s" % _OUTPUT_PATH}

    stats = _count_slot_stats(occ, slot_items)
    h, w = overlay.shape[:2]
    return {
        "ok": True,
        "mode": mode,
        "path": str(_OUTPUT_PATH),
        "width": w,
        "height": h,
        **stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a one-shot Exodia debug frame.")
    parser.add_argument(
        "--mode",
        choices=_MODES,
        default="inventory_identify",
        help="overlay style (default: inventory_identify)",
    )
    args = parser.parse_args()
    _ensure_capture_env()
    result = render_debug_frame(args.mode)
    _emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
