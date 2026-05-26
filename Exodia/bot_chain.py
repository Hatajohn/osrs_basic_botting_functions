"""
Single-step action dispatch for Exodia desktop UI and ``exodia_chain.py``.

Phase 3: one block id → one primitive (click template, use item on item by label).
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bot_actions as Actions
import bot_env as Env
from bot_client_config import load_client_rect
from bot_eyes import inventory_slot_client_center, inventory_slot_screen_xy
from bot_inventory_actions import (
    closest_slot,
    focus_runelite,
    slots_matching_item,
    use_named_item_on_named_item,
)
from bot_inventory_detect import bind_inventory_to_eyes, inventory_occupancy_from_client
from bot_inventory_items import identify_inventory_slot_items
from bot_template_targets import (
    filter_matches_outside_inventory,
    playspace_search_roi,
    slot_label_for_match,
)

Rect = List[int]

__all__ = ["dispatch", "make_session"]


def _fail(error: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "error": error}
    out.update(extra)
    return out


def _ok(**extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True}
    out.update(extra)
    return out


def _ensure_capture_env() -> None:
    ps_path = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.path.isfile(ps_path):
        if not os.environ.get("EXODIA_CAPTURE_BACKEND"):
            os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
        if not os.environ.get("EXODIA_INPUT_BACKEND"):
            os.environ["EXODIA_INPUT_BACKEND"] = "wsl_ps"
    os.environ.setdefault("EXODIA_INV_FRAME_BUCKETS", "1")


def _frame_display_scale(frame_w: int, frame_h: int) -> Tuple[float, int, int]:
    """Scale factor and display size matching ``exodia_debug_frame`` ``raw_client`` output."""
    display_w, display_h = int(frame_w), int(frame_h)
    scale = 1.0
    max_width = int(os.environ.get("EXODIA_DEBUG_FRAME_MAX_WIDTH", "640") or "640")
    if frame_w > max_width > 0:
        scale = max_width / float(frame_w)
        display_w = max(1, int(round(frame_w * scale)))
        display_h = max(1, int(round(frame_h * scale)))
    return scale, display_w, display_h


def _scale_client_point(xy: Tuple[int, int], scale: float) -> List[int]:
    return [int(round(xy[0] * scale)), int(round(xy[1] * scale))]


def _click_target_payload(client, eyes, best_match) -> Dict[str, Any]:
    """Geometry for UI overlay (aligned with scaled ``raw_client`` debug frame in the UI)."""
    cr = [int(v) for v in client.win_rect]
    sx, sy = int(best_match.screen_xy[0]), int(best_match.screen_xy[1])
    click_client = (sx - cr[0], sy - cr[1])
    frame_h = frame_w = 0
    if eyes.curr_client is not None and getattr(eyes.curr_client, "size", 0) > 0:
        frame_h, frame_w = eyes.curr_client.shape[:2]

    scale, display_w, display_h = _frame_display_scale(int(frame_w), int(frame_h))
    display_xy = _scale_client_point(click_client, scale)

    return {
        "screen_xy": [sx, sy],
        "click_client_xy": display_xy,
        "frame_width": display_w,
        "frame_height": display_h,
        "client_rect": cr,
    }


def _resolve_use_on_slots(
    slot_items: Sequence[Sequence[Optional[str]]],
    source_id: str,
    dest_id: str,
) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]], Optional[str]]:
    """Pick source/dest slots the same way as ``use_named_item_on_named_item``."""
    src_candidates = slots_matching_item(slot_items, source_id)
    dst_candidates = slots_matching_item(slot_items, dest_id)
    if not src_candidates:
        return None, None, "source_not_found"
    src = sorted(src_candidates, key=lambda s: (s[0], s[1]))[0]
    dst_pool = [s for s in dst_candidates if s != src]
    if not dst_pool:
        return src, None, "dest_not_found"
    dst = closest_slot(src, dst_pool)
    if dst is None:
        return src, None, "dest_not_found"
    return src, dst, None


def _use_on_preview_payload(
    eyes,
    inv_rect: Sequence[int],
    client_rect: Sequence[int],
    src: Tuple[int, int],
    dst: Tuple[int, int],
    *,
    source_id: str,
    dest_id: str,
) -> Dict[str, Any]:
    from_center = inventory_slot_client_center(inv_rect, src[0], src[1])
    to_center = inventory_slot_client_center(inv_rect, dst[0], dst[1])
    if from_center is None or to_center is None:
        return {}

    frame_h = frame_w = 0
    if eyes.curr_client is not None and getattr(eyes.curr_client, "size", 0) > 0:
        frame_h, frame_w = eyes.curr_client.shape[:2]
    scale, display_w, display_h = _frame_display_scale(int(frame_w), int(frame_h))

    from_screen = inventory_slot_screen_xy(inv_rect, client_rect, src[0], src[1])
    to_screen = inventory_slot_screen_xy(inv_rect, client_rect, dst[0], dst[1])

    return {
        "previewMode": "use_on",
        "from_click_client_xy": _scale_client_point(from_center, scale),
        "to_click_client_xy": _scale_client_point(to_center, scale),
        "from_screen_xy": list(from_screen) if from_screen else None,
        "to_screen_xy": list(to_screen) if to_screen else None,
        "frame_width": display_w,
        "frame_height": display_h,
        "sourceId": source_id,
        "destId": dest_id,
        "source_slot": list(src),
        "dest_slot": list(dst),
        "label": "%s → %s" % (source_id, dest_id),
        "searchMode": "inventory",
    }


def make_session() -> Tuple[Any, Any, Any, Optional[str]]:
    """Return ``(client, eyes, arms, error)`` using ``client_rect.json``."""
    _ensure_capture_env()
    win_rect = load_client_rect()
    if not win_rect or len(win_rect) != 4:
        return None, None, None, "missing or invalid client_rect.json"
    client, eyes, arms = Actions.bot_init(win_rect=win_rect)
    return client, eyes, arms, None


def _dispatch_click_template(
    client,
    eyes,
    arms,
    *,
    template: str,
    template_path: Optional[str],
    inv: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    template = (template or "").strip()
    if not template:
        return _fail("missing_template")
    tpl_path = (template_path or "").strip() or None

    Actions.bot_update(client, eyes)
    search_roi = None
    if inv:
        inv_rect = bind_inventory_to_eyes(eyes, refresh_client=False, force=True)
        if not inv_rect or len(inv_rect) != 4:
            return _fail(
                "inventory_not_found",
                hint="open inventory in RuneLite or recalibrate client_rect.json",
            )
        if eyes.curr_inventory is None or getattr(eyes.curr_inventory, "size", 0) == 0:
            return _fail("no_inventory_crop", hint="inventory panel not visible in capture")
    else:
        bind_inventory_to_eyes(eyes, refresh_client=False, force=False)
        search_roi = playspace_search_roi(eyes)

    detailed = eyes.locate_image_detailed(
        filename=template,
        inv=inv,
        template_path=tpl_path,
        search_roi=search_roi,
    )
    matches = list(detailed.matches) if detailed.found else []
    excluded_inv = 0
    if not inv:
        matches, excluded_inv = filter_matches_outside_inventory(eyes, matches)
        if excluded_inv:
            print(
                "click_template_world: excluded %d match(es) inside inventory panel"
                % excluded_inv,
                flush=True,
            )

    if not matches:
        err = detailed.error or "template_not_found"
        world_hint = (
            "playspace search excludes inventory; use images/osrs_infernalEel.png "
            "(fishing spot) for Click outside, or items/infernal_eel.png for Click in inventory"
        )
        inv_hint = "item not in inventory or template does not match live slots"
        return _fail(
            err if err in ("no_inventory_crop", "missing_template", "empty_image") else "template_not_found",
            template=template,
            inv=inv,
            templatePath=tpl_path,
            excludedInventoryMatches=excluded_inv if not inv else None,
            hint=inv_hint if inv else world_hint,
        )

    best = max(matches, key=lambda m: m.score)
    match_count = len(matches)
    slot_label = slot_label_for_match(eyes, best) if inv else None

    if dry_run:
        return _ok(
            dry_run=True,
            template=template,
            inv=inv,
            matches=match_count,
            templatePath=tpl_path,
            score=round(float(best.score), 4),
            input_backend=Env.input_backend_label(),
            searchMode="inventory" if inv else "playspace",
            slot=slot_label,
            excludedInventoryMatches=excluded_inv if not inv else None,
            **_click_target_payload(client, eyes, best),
        )

    mode = "click_template_inv" if inv else "click_template_world"
    print(
        "%s: input=%s focus=RuneLite click=%s score=%.3f matches=%d%s"
        % (
            mode,
            Env.input_backend_label(),
            best.screen_xy,
            best.score,
            match_count,
            (" slot " + slot_label) if slot_label else "",
        ),
        flush=True,
    )
    if Env.input_backend_label() != "wsl_ps":
        print(
            "click_template: WARNING — EXODIA_INPUT_BACKEND is not wsl_ps; "
            "clicks may not reach Windows RuneLite from WSL",
            flush=True,
        )

    focus_runelite()
    time.sleep(0.2)
    arms.click_at(best.screen_xy)
    time.sleep(0.05)

    return _ok(
        template=template,
        inv=inv,
        templatePath=tpl_path,
        score=round(float(best.score), 4),
        matches=match_count,
        input_backend=Env.input_backend_label(),
        searchMode="inventory" if inv else "playspace",
        slot=slot_label,
        excludedInventoryMatches=excluded_inv if not inv else None,
        **_click_target_payload(client, eyes, best),
    )


def _dispatch_use_item_id_on_item_id(
    client,
    eyes,
    arms,
    *,
    source_id: str,
    dest_id: str,
    dry_run: bool,
) -> Dict[str, Any]:
    source_id = (source_id or "").strip()
    dest_id = (dest_id or "").strip()
    if not source_id or not dest_id:
        return _fail("missing_source_or_dest")

    Actions.bot_update(client, eyes)
    inv_rect = bind_inventory_to_eyes(eyes, refresh_client=False, force=True)
    if not inv_rect or len(inv_rect) != 4:
        return _fail("inventory_not_found", hint="open inventory in RuneLite")

    client_bgr = eyes.curr_client
    if client_bgr is None or getattr(client_bgr, "size", 0) == 0:
        return _fail("no_client_frame")

    occ, _count, _proto = inventory_occupancy_from_client(client_bgr, inv_rect)
    if occ is None:
        return _fail("occupancy_failed")

    slot_items, _, _ = identify_inventory_slot_items(
        client_bgr,
        inv_rect,
        occ,
        frame_buckets=True,
    )
    if slot_items is None:
        return _fail("identify_failed")

    client_rect = eyes.client_rect or list(client.win_rect)
    src, dst, slot_err = _resolve_use_on_slots(slot_items, source_id, dest_id)
    if slot_err:
        return _fail(
            slot_err,
            missing_item=source_id if slot_err == "source_not_found" else dest_id,
            sourceId=source_id,
            destId=dest_id,
            source_slot=list(src) if src else None,
        )

    preview = _use_on_preview_payload(
        eyes,
        inv_rect,
        client_rect,
        src,
        dst,
        source_id=source_id,
        dest_id=dest_id,
    )
    if dry_run:
        src_slots = slots_matching_item(slot_items, source_id)
        dst_slots = slots_matching_item(slot_items, dest_id)
        return _ok(
            dry_run=True,
            sourceSlots=len(src_slots),
            destSlots=len(dst_slots),
            **preview,
        )

    result = use_named_item_on_named_item(
        inv_rect,
        client_rect,
        slot_items,
        source_id,
        dest_id,
        arms=arms,
    )
    if not result.ok:
        return _fail(
            result.reason or "use_on_failed",
            missing_item=result.missing_item,
            sourceId=source_id,
            destId=dest_id,
        )
    return _ok(
        **preview,
        source_slot=list(result.source_slot) if result.source_slot else None,
        dest_slot=list(result.dest_slot) if result.dest_slot else None,
    )


def dispatch(block_id: str, args: Optional[Dict[str, Any]] = None, *, dry_run: bool = False) -> Dict[str, Any]:
    """
    Run one action block. Returns ``{ ok, result?, error?, ... }`` (no duration_ms; CLI adds it).
    """
    args = args or {}
    block_id = (block_id or "").strip()
    if not block_id:
        return _fail("missing_block_id")

    client, eyes, arms, session_err = make_session()
    if session_err:
        return _fail(session_err, hint="calibrate client rect and ensure RuneLite is visible")

    tpl_path = str(args.get("templatePath", args.get("template_path", "")) or "").strip() or None

    if block_id == "click_template_world":
        return _dispatch_click_template(
            client,
            eyes,
            arms,
            template=str(args.get("template", "")),
            template_path=tpl_path,
            inv=False,
            dry_run=dry_run,
        )
    if block_id == "click_template_inv":
        return _dispatch_click_template(
            client,
            eyes,
            arms,
            template=str(args.get("template", "")),
            template_path=tpl_path,
            inv=True,
            dry_run=dry_run,
        )
    if block_id == "use_item_id_on_item_id":
        return _dispatch_use_item_id_on_item_id(
            client,
            eyes,
            arms,
            source_id=str(args.get("sourceId", args.get("source_id", ""))),
            dest_id=str(args.get("destId", args.get("dest_id", ""))),
            dry_run=dry_run,
        )

    return _fail("unknown_block", block_id=block_id)
