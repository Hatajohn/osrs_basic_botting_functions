#!/usr/bin/env python3
"""
One-shot sacred eel perception diagnostic (no clicks).

Writes snapshots under Exodia/logs/diag/ and prints a health report.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_EXODIA = Path(__file__).resolve().parent.parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

# Botting/ cwd for images/
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
from .sacred_eel_fsm import EEL_ITEM_NAME, KNIFE_ITEM_NAME
from .sacred_eel_log import LOGS_DIR, ensure_logs_dir


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

    print("=== sacred eel diagnose ===")
    print("cwd:", os.getcwd())
    print("client_rect:", rect)
    print("capture:", os.environ.get("EXODIA_CAPTURE_BACKEND", "mss"))
    print("eel item label:", EEL_ITEM_NAME)
    print("knife item label:", KNIFE_ITEM_NAME)

    templates = [
        "osrs_sacredEelSpot.png",
        "osrs_sacredEelSpot2.png",
        "osrs_sacredEel.png",
        "osrs_knife.png",
        "ui_icons.png",
        "Fishing_text.png",
        "Not_fishing_text.png",
    ]
    missing = [t for t in templates if not Path("images", t).is_file()]
    if missing:
        print("FAIL: missing templates:", ", ".join(missing))
    else:
        print("OK: all templates present")

    for stem in (EEL_ITEM_NAME, KNIFE_ITEM_NAME):
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

    bot_e.find_action_strip_rect(refresh_client=False)
    ax, ay, aw, ah = bot_e.action_strip_roi_client()
    src = "template" if bot_e.action_strip_rect else "left-of-inv"
    print("action_strip_roi (%s): [%d, %d, %d, %d]" % (src, ax, ay, aw, ah))
    strip = frame[ay : ay + ah, ax : ax + aw]
    if strip.size:
        cv2.imwrite(str(diag_dir / "action_strip.png"), strip)

    from bot_spot_verify import default_spot_verify_config, locate_sacred_eel_spots

    spot_thr = float(os.environ.get("EXODIA_SPOT_THRESHOLD", "0.45"))
    cfg = default_spot_verify_config()
    print(
        "spot verify: enabled=%s eel=%s cyan=%s icon=%s"
        % (cfg.enabled, cfg.require_eel_icon, cfg.require_cyan_outline, cfg.eel_icon_file)
    )
    verified = locate_sacred_eel_spots(
        bot_e,
        ["osrs_sacredEelSpot.png", "osrs_sacredEelSpot2.png"],
        threshold=spot_thr,
        verify_cfg=cfg,
    )
    print("verified sacred spots:", len(verified), "(thr=%.2f)" % spot_thr)
    for i, c in enumerate(verified[:5]):
        print(
            "  [%d] spot=%.2f eel=%.2f cyan=%.3f tpl=%s click=%s"
            % (i, c.spot_score, c.eel_score, c.cyan_ratio, c.template, c.click_xy)
        )

    slot_items, occ = read_inventory_labels(bot_e)
    eel_slots = count_labeled_item_slots(slot_items, occ, EEL_ITEM_NAME)
    n = occupied_cell_count(occ)
    full = inventory_is_full(bot_e)
    print("eel labeled slots:", eel_slots, "| occupied:", n, "/ 28 | inv_full:", full)
    buckets = slot_label_bucket_counts(slot_items, occ)
    for label, count in buckets[:12]:
        print("  bucket %s x%d" % (label, count))

    from bot_inventory_count import count_inventory_quantity, count_inventory_stacks

    from bot_inventory_count import _default_threshold

    eel_thr = _default_threshold()
    qty = count_inventory_quantity(bot_e, "osrs_sacredEel.png", threshold=eel_thr)
    stacks = count_inventory_stacks(bot_e, "osrs_sacredEel.png", threshold=eel_thr)
    panel = bot_e._inventory_panel_bgr_for_slots()
    panel_wh = "%dx%d" % (panel.shape[1], panel.shape[0]) if panel is not None and panel.size else "?"
    print(
        "legacy template count: %d total (stack qty, thr=%.2f) | %d icon regions | panel %s"
        % (qty, eel_thr, stacks, panel_wh)
    )
    if eel_slots <= 3 and occ and sum(1 for r in occ for c in r if c) >= 6:
        print(
            "WARN: many occupied slots but low eel label count — check items/%s.png "
            "or EXODIA_INV_PANEL_WIDTH=205 / EXODIA_INV_PANEL_RECT=L,T,W,H"
            % EEL_ITEM_NAME
        )
    for name, inv_flag, fname, thr in [
        ("knife", True, "osrs_knife.png", 0.35),
    ]:
        hits = bot_e.locate_image(
            filename=fname,
            inv=inv_flag,
            name="diag-" + name,
            threshold=thr,
        )
        print("locate %s: %d raw hit(s) (thr=%.2f)" % (name, len(hits) if hits else 0, thr))

    try:
        from bot_overlay import draw_bot_overlay

        ov = draw_bot_overlay(
            bot_e,
            action_code=code,
            eel_count=eel_slots,
            inv_slots=n,
            spot_clicks=[c.click_xy for c in verified] if verified else None,
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
