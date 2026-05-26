#!/usr/bin/env python3
"""
One-shot infernal eel perception diagnostic (no clicks).

Writes snapshots under Exodia/logs/diag/ and prints a health report.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_EXODIA = Path(__file__).resolve().parent.parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

_BOTTING = _EXODIA.parent
if (_BOTTING / "images").is_dir():
    os.chdir(_BOTTING)

import cv2
import bot_actions as Actions
import bot_client as Client
from bot_client_config import load_client_rect
from bot_gamestate import inventory_is_full, occupied_cell_count
from bot_inventory_items import (
    count_labeled_item_slots,
    read_inventory_labels,
    slot_label_bucket_counts,
)
from .infernal_eel_fsm import (
    EEL_ITEM_NAME,
    HAMMER_ITEM_NAME,
    SPOT_TEMPLATES,
    SPOT_TEMPLATE_THRESHOLD,
    _locate_spots,
)
from .infernal_eel_log import LOGS_DIR, ensure_logs_dir


def _enable_wsl_ps() -> None:
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file():
        os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
        os.environ.setdefault("EXODIA_INPUT_BACKEND", "wsl_ps")


def main() -> int:
    _enable_wsl_ps()
    ensure_logs_dir()
    diag_dir = LOGS_DIR / "diag"
    diag_dir.mkdir(parents=True, exist_ok=True)

    rect = load_client_rect()
    if not rect:
        print("FAIL: no client_rect.json — run calibrate_client_rect.py")
        return 1

    print("=== infernal eel diagnose ===")
    print("cwd:", os.getcwd())
    print("client_rect:", rect)
    print("capture:", os.environ.get("EXODIA_CAPTURE_BACKEND", "mss"))
    print("eel item label:", EEL_ITEM_NAME)
    print("hammer item label:", HAMMER_ITEM_NAME)

    templates = SPOT_TEMPLATES + ["ui_icons.png", "Fishing_text.png", "Not_fishing_text.png"]
    missing = [t for t in templates if not Path("images", t).is_file()]
    if missing:
        print("WARN: missing spot/UI templates:", ", ".join(missing))
    else:
        print("OK: spot/UI templates present")

    for stem in (EEL_ITEM_NAME, HAMMER_ITEM_NAME):
        p = Path("items") / ("%s.png" % stem)
        print("item template %s: %s" % (stem, "OK" if p.is_file() else "MISSING"))

    try:
        client, bot_e, _bot_a = Actions.bot_init(win_rect=rect)
    except Client.RuneLiteNotFoundException as exc:
        print("FAIL: client init:", exc)
        return 1

    Actions.bot_update(client, bot_e)
    frame = bot_e.curr_client
    if frame is None or frame.size == 0:
        print("FAIL: blank client capture")
        return 1

    mean = float(frame.mean())
    cv2.imwrite(str(diag_dir / "client.png"), frame)
    print("OK: client capture mean=%.1f shape=%s -> %s" % (mean, frame.shape, diag_dir / "client.png"))

    if mean < 2.0:
        print("WARN: capture very dark — check client_rect / RuneLite visible")

    from bot_inventory_detect import validate_inventory_rect

    inv = bot_e.inventory_rect
    if inv:
        inv_score = validate_inventory_rect(bot_e.curr_client, inv)
        print("OK: inventory_rect", inv, "(grid score %.1f)" % inv_score)
        if bot_e.curr_inventory is not None:
            cv2.imwrite(str(diag_dir / "inventory.png"), bot_e.curr_inventory)
    else:
        print("WARN: inventory not calibrated (ui_icons.png match failed)")

    code = bot_e.get_action_text(refresh=False)
    labels = {0: "FISHING (green)", 1: "IDLE (red)", 2: "no fishing UI (seek spot)"}
    print("action line:", code, labels.get(code, "?"))

    slot_items, occ = read_inventory_labels(bot_e)
    eel_slots = count_labeled_item_slots(slot_items, occ, EEL_ITEM_NAME)
    n = occupied_cell_count(occ)
    full = inventory_is_full(bot_e)
    print("eel labeled slots:", eel_slots, "| occupied:", n, "/ 28 | inv_full:", full)
    buckets = slot_label_bucket_counts(slot_items, occ)
    for label, count in buckets[:12]:
        print("  bucket %s x%d" % (label, count))

    spots = _locate_spots(bot_e)
    print("infernal spot hits:", len(spots), "(thr=%.2f)" % SPOT_TEMPLATE_THRESHOLD)
    for i, pt in enumerate(spots[:5]):
        print("  [%d] click=%s" % (i, pt))

    try:
        from bot_overlay import draw_bot_overlay

        ov = draw_bot_overlay(
            bot_e,
            action_code=code_robust,
            eel_count=eel_slots,
            inv_slots=n,
            spot_clicks=spots if spots else None,
        )
        if ov is not None:
            p = diag_dir / "overlay.png"
            cv2.imwrite(str(p), ov)
            print("OK: overlay ->", p)
    except Exception as exc:
        print("WARN: overlay:", exc)

    print("=== diagnose done — see", diag_dir, "===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
