"""
Single-step action dispatch for Exodia desktop UI and ``exodia_chain.py``.

Phase 3: one block id → one primitive (click template, use item on item by label).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bot_actions as Actions
import bot_env as Env
from bot_client_config import load_client_rect
from bot_eyes import TemplateMatch, inventory_slot_client_center, inventory_slot_screen_xy
from bot_inventory_actions import (
    closest_slot,
    focus_runelite,
    pick_distinct_screen_points,
    slots_matching_item,
    use_named_item_on_named_item,
)
from bot_inventory_detect import bind_inventory_to_eyes, inventory_occupancy_from_client
from bot_inventory_items import (
    identify_inventory_slot_items,
    locate_named_template_in_inventory,
    resolve_inventory_template_path,
    slot_at_client_point,
)
from bot_stream_client import (
    StreamSnapshot,
    apply_stream_snapshot_to_eyes,
    configure_action_stream_env,
    fetch_stream_snapshot,
    refresh_action_frame,
    refresh_stream_snapshot_if_stale,
    stream_expected,
    stream_snapshot_usable,
    sync_inventory_geometry_from_snap,
    world_hit_for_template,
)
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


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _click_world_cyan_first() -> bool:
    """Optional: gate on RuneLite cyan tile markers (off by default — use shape match)."""
    return _env_bool("EXODIA_CLICK_WORLD_CYAN_FIRST", False)


def _locate_world_shape_matches(
    eyes,
    template: str,
    tpl_path: Optional[str],
    search_roi: Optional[List[int]],
) -> Tuple[List[TemplateMatch], int, Optional[str], Dict[str, Any]]:
    from bot_shape_match import shape_preprocess_playspace, shape_match_threshold

    detailed = eyes.locate_image_detailed(
        filename=template,
        inv=False,
        template_path=tpl_path,
        search_roi=search_roi,
        threshold=shape_match_threshold(),
        shape_preprocess=shape_preprocess_playspace(),
        shape_playspace=True,
    )
    matches = list(detailed.matches) if detailed.found else []
    matches, excluded_inv = filter_matches_outside_inventory(eyes, matches)
    err = None if matches else (detailed.error or "template_not_found")
    return (
        matches,
        excluded_inv,
        err,
        {"locateMode": "shape", "shapeMatch": shape_preprocess_playspace()},
    )


def _click_world_playspace_fallback() -> bool:
    return _env_bool("EXODIA_CLICK_WORLD_FALLBACK", True)


def _locate_world_template_matches(
    eyes,
    template: str,
    tpl_path: Optional[str],
) -> Tuple[List[TemplateMatch], int, Optional[str], Dict[str, Any]]:
    from bot_world_objects import locate_world_objects_from_eyes, resolve_world_template_file, world_match_threshold

    stem, path = resolve_world_template_file(template, tpl_path)
    if not path:
        return [], 0, "missing_template", {"locateMode": "cyan_first"}

    wo = locate_world_objects_from_eyes(
        eyes,
        [stem],
        threshold=world_match_threshold(),
        template_paths={stem: path},
    )
    matches = [
        TemplateMatch(
            screen_xy=h.screen_xy[:],
            client_xy=h.client_xy[:],
            score=float(h.score),
        )
        for h in wo.hits
    ]
    meta = {
        "locateMode": "cyan_first",
        "cyanMarkers": len(wo.cyan_regions),
        "cyanRejected": wo.cyan_rejected,
    }
    return matches, wo.inventory_filtered, None, meta


def _overlay_max_width(meta: Optional[Dict] = None) -> int:
    if meta and isinstance(meta, dict):
        raw = meta.get("overlay_max_width")
        if raw is not None:
            try:
                width = int(raw)
            except (TypeError, ValueError):
                width = 0
            if width > 0:
                return width
    return int(os.environ.get("EXODIA_DEBUG_FRAME_MAX_WIDTH", "640") or "640")


def _refresh_from_stream(client, eyes) -> Tuple[Optional[StreamSnapshot], Optional[str]]:
    return refresh_action_frame(client, eyes)


def _apply_pre_click_stream_refresh(
    client,
    eyes,
    snap: Optional[StreamSnapshot],
    stream_meta: Optional[Dict],
    frame_payload: Dict[str, Any],
) -> Tuple[Optional[StreamSnapshot], Optional[Dict], Dict[str, Any]]:
    """Re-fetch pristine snapshot when frame age exceeds threshold before physical click."""
    if snap is None or snap.frame is None or not stream_expected():
        return snap, stream_meta, frame_payload
    fresh = refresh_stream_snapshot_if_stale(client, eyes, snap)
    if fresh is not snap:
        snap = fresh
        stream_meta = snap.meta
        frame_payload = _frame_meta_payload(snap, eyes, meta=stream_meta)
    return snap, stream_meta, frame_payload


def _frame_meta_payload(
    snap: Optional[StreamSnapshot],
    eyes,
    meta: Optional[Dict] = None,
) -> Dict[str, Any]:
    root_meta = meta if meta is not None else (snap.meta if snap is not None else None)
    max_w = _overlay_max_width(root_meta)

    source_w = source_h = 0
    capture_seq: Optional[int] = None
    frame_age_ms: Optional[float] = None
    source: Optional[str] = None

    if snap is not None and snap.frame is not None:
        capture_seq = int(snap.frame.capture_seq)
        source_w = int(snap.frame.width)
        source_h = int(snap.frame.height)
        frame_age_ms = float(snap.frame.frame_age_ms)
        source = str(snap.frame.source)
    elif eyes.curr_client is not None and getattr(eyes.curr_client, "size", 0) > 0:
        source_h, source_w = eyes.curr_client.shape[:2]

    scale, display_w, display_h = _frame_display_scale(source_w, source_h, max_width=max_w)
    payload: Dict[str, Any] = {
        "frame_width": display_w,
        "frame_height": display_h,
        "overlay_max_width": max_w,
    }
    if capture_seq is not None:
        payload["capture_seq"] = capture_seq
    if source_w > 0 and source_h > 0:
        payload["frame_source_width"] = source_w
        payload["frame_source_height"] = source_h
    if frame_age_ms is not None:
        payload["frame_age_ms"] = round(frame_age_ms, 1)
    if source:
        payload["source"] = source
    return payload


def _merge_action_payload(*parts: Dict[str, Any]) -> Dict[str, Any]:
    """Merge action result dicts; later parts win on duplicate keys."""
    out: Dict[str, Any] = {}
    for part in parts:
        if part:
            out.update(part)
    return out


def _stream_fail_hint(error: str) -> Optional[str]:
    if error == "stream_frame_unavailable":
        return "Restart stream"
    if error == "stream_meta_stale":
        return "Hard reset stream"
    if error == "stream_inventory_unavailable":
        return "Wait for stream inventory labels or Re-analyze"
    return None


def _template_item_stem(template: str, tpl_path: Optional[str]) -> str:
    resolved = resolve_inventory_template_path(template, tpl_path)
    stem = Path(resolved).stem if resolved else (template or "").strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    return stem.lower()


def _inventory_matches_from_stream_cache(
    eyes,
    client,
    snap: StreamSnapshot,
    template: str,
    tpl_path: Optional[str],
) -> List[TemplateMatch]:
    """Build click targets from stream ``slot_items`` labels (no template re-match)."""
    from bot_inventory_actions import slots_matching_item
    from bot_eyes import inventory_slot_client_center, inventory_slot_screen_xy

    slot_items, occ = _inventory_grid_from_snap(snap, eyes)
    if slot_items is None:
        return []
    inv_rect = eyes.inventory_rect
    if inv_rect is None or len(inv_rect) != 4:
        return []
    client_rect = list(client.win_rect)
    stem = _template_item_stem(template, tpl_path)
    matches: List[TemplateMatch] = []
    for row, col in slots_matching_item(slot_items, stem):
        if occ is not None:
            if row >= len(occ) or col >= len(occ[row]) or not occ[row][col]:
                continue
        center = inventory_slot_client_center(inv_rect, row, col)
        screen = inventory_slot_screen_xy(inv_rect, client_rect, row, col)
        if center is None or screen is None:
            continue
        matches.append(
            TemplateMatch(
                screen_xy=[int(screen[0]), int(screen[1])],
                client_xy=[int(center[0]), int(center[1])],
                score=1.0,
            )
        )
    return matches


def _sync_playspace_inventory_from_stream(eyes, snap: Optional[StreamSnapshot]) -> None:
    """Set inventory rect for playspace ROI exclusion from stream only (no grab)."""
    if snap is None:
        return
    if eyes.inventory_rect is not None and len(eyes.inventory_rect) == 4:
        eyes._sync_inventory_global()
        return
    sync_inventory_geometry_from_snap(eyes, snap)


def _ensure_capture_env() -> None:
    configure_action_stream_env()
    ps_path = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.path.isfile(ps_path):
        if not os.environ.get("EXODIA_CAPTURE_BACKEND"):
            os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
        if not os.environ.get("EXODIA_INPUT_BACKEND"):
            os.environ["EXODIA_INPUT_BACKEND"] = "wsl_ps"
    os.environ.setdefault("EXODIA_INV_FRAME_BUCKETS", "1")
    os.environ.setdefault("EXODIA_STREAM_PORT", "8765")


def _frame_display_scale(
    frame_w: int,
    frame_h: int,
    *,
    max_width: Optional[int] = None,
) -> Tuple[float, int, int]:
    """Scale factor and display size matching ``exodia_debug_frame`` ``raw_client`` output."""
    display_w, display_h = int(frame_w), int(frame_h)
    scale = 1.0
    if max_width is None:
        max_width = _overlay_max_width(None)
    if frame_w > max_width > 0:
        scale = max_width / float(frame_w)
        display_w = max(1, int(round(frame_w * scale)))
        display_h = max(1, int(round(frame_h * scale)))
    return scale, display_w, display_h


def _scale_client_point(xy: Tuple[int, int], scale: float) -> List[int]:
    return [int(round(xy[0] * scale)), int(round(xy[1] * scale))]


def _click_target_payload(
    client,
    eyes,
    best_match,
    all_matches: Optional[Sequence[Any]] = None,
    *,
    max_width: Optional[int] = None,
) -> Dict[str, Any]:
    """Geometry for UI overlay (aligned with scaled ``raw_client`` debug frame in the UI)."""
    cr = [int(v) for v in client.win_rect]
    sx, sy = int(best_match.screen_xy[0]), int(best_match.screen_xy[1])
    click_client = (sx - cr[0], sy - cr[1])
    frame_h = frame_w = 0
    if eyes.curr_client is not None and getattr(eyes.curr_client, "size", 0) > 0:
        frame_h, frame_w = eyes.curr_client.shape[:2]

    scale, display_w, display_h = _frame_display_scale(
        int(frame_w),
        int(frame_h),
        max_width=max_width,
    )
    display_xy = _scale_client_point(click_client, scale)

    payload: Dict[str, Any] = {
        "screen_xy": [sx, sy],
        "click_client_xy": display_xy,
        "frame_width": display_w,
        "frame_height": display_h,
        "client_rect": cr,
    }

    pool = list(all_matches) if all_matches else [best_match]
    if len(pool) > 1:
        best_key = (sx, sy)
        candidates: List[Dict[str, Any]] = []
        for m in pool:
            msx, msy = int(m.screen_xy[0]), int(m.screen_xy[1])
            m_client = (msx - cr[0], msy - cr[1])
            candidates.append(
                {
                    "click_client_xy": _scale_client_point(m_client, scale),
                    "screen_xy": [msx, msy],
                    "score": round(float(m.score), 4),
                    "selected": (msx, msy) == best_key,
                }
            )
        payload["match_candidates"] = candidates
        payload["match_count"] = len(candidates)

    return payload


def _stream_identify_wait_ms() -> int:
    try:
        return max(0, int(os.environ.get("EXODIA_STREAM_IDENTIFY_WAIT_MS", "800") or "800"))
    except (TypeError, ValueError):
        return 800


def _inventory_grid_from_snap(
    snap: Optional[StreamSnapshot],
    eyes,
) -> Tuple[Optional[List[List[Optional[str]]]], Optional[List[List[bool]]]]:
    inv = (snap.inventory if snap is not None else None) or {}
    slot_items = inv.get("slot_items")
    occupancy = inv.get("occupancy")
    pe = getattr(eyes, "perception_envelope", None) or {}
    if slot_items is None:
        slot_items = pe.get("inventory_slot_items")
    if occupancy is None:
        occupancy = pe.get("inventory_slot_occupancy")
    if not isinstance(slot_items, list) or not slot_items:
        return None, None
    if not isinstance(occupancy, list) or not occupancy:
        return None, None
    try:
        grid = [[cell for cell in row] for row in slot_items]
        occ = [[bool(cell) for cell in row] for row in occupancy]
    except (TypeError, ValueError):
        return None, None
    return grid, occ


def _inventory_cache_pending(
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Sequence[Sequence[Any]],
) -> bool:
    rows = min(len(slot_items), len(occupancy))
    for row in range(rows):
        cols = min(len(slot_items[row]), len(occupancy[row]))
        for col in range(cols):
            if not occupancy[row][col]:
                continue
            if slot_items[row][col] == "?":
                return True
    return False


def _poll_stream_inventory_cache(
    client,
    eyes,
    snap: StreamSnapshot,
    *,
    source_id: str,
    dest_id: str,
) -> Tuple[StreamSnapshot, Dict[str, Any], List[List[Optional[str]]], List[List[bool]]]:
    """Refresh stream cache while occupied slots still carry ``?`` labels."""
    stream_meta = snap.meta
    frame_payload = _frame_meta_payload(snap, eyes, meta=stream_meta)
    slot_items, occ = _inventory_grid_from_snap(snap, eyes)
    if slot_items is None or occ is None:
        return snap, frame_payload, slot_items or [], occ or []

    wait_ms = _stream_identify_wait_ms()
    if wait_ms <= 0 or not _inventory_cache_pending(slot_items, occ):
        return snap, frame_payload, slot_items, occ

    deadline = time.monotonic() + wait_ms / 1000.0
    while time.monotonic() < deadline:
        src, dst, _ = _resolve_use_on_slots(slot_items, source_id, dest_id)
        if src is not None and dst is not None:
            break
        if not _inventory_cache_pending(slot_items, occ):
            break
        time.sleep(0.2)
        fresh = fetch_stream_snapshot()
        if fresh is None:
            continue
        ok, _ = stream_snapshot_usable(fresh, require_calibrated=True)
        if not ok:
            continue
        apply_stream_snapshot_to_eyes(eyes, fresh, client_rect=list(client.win_rect))
        snap = fresh
        stream_meta = snap.meta
        frame_payload = _frame_meta_payload(snap, eyes, meta=stream_meta)
        parsed_items, parsed_occ = _inventory_grid_from_snap(snap, eyes)
        if parsed_items is not None and parsed_occ is not None:
            slot_items, occ = parsed_items, parsed_occ

    return snap, frame_payload, slot_items, occ


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


def _use_on_template_for_id(item_id: str, template: Optional[str]) -> str:
    tpl = (template or "").strip()
    if tpl:
        return tpl
    stem = (item_id or "").strip()
    return ("%s.png" % stem) if stem else ""


def _resolve_use_on_via_templates(
    client_bgr,
    inv_rect: Sequence[int],
    client_rect: Sequence[int],
    *,
    source_template: str,
    source_template_path: Optional[str],
    dest_template: str,
    dest_template_path: Optional[str],
    occupancy: Optional[Sequence[Sequence[bool]]] = None,
) -> Tuple[
    Optional[Tuple[int, int]],
    Optional[Tuple[int, int]],
    Optional[Tuple[int, int]],
    Optional[Tuple[int, int]],
    Optional[str],
]:
    """Resolve use-on slots via per-slot template scoring (same path as Find in inventory)."""
    from bot_shape_match import inventory_template_threshold

    if client_bgr is None or getattr(client_bgr, "size", 0) == 0:
        return None, None, None, None, "no_client_frame"
    if not inv_rect or len(inv_rect) != 4:
        return None, None, None, None, "inventory_not_found"

    thr = inventory_template_threshold()
    src_matches, _src_err = locate_named_template_in_inventory(
        client_bgr,
        inv_rect,
        client_rect,
        source_template,
        template_path=source_template_path,
        threshold=thr,
    )
    if not src_matches:
        return None, None, None, None, "source_not_found"

    dst_matches, _dst_err = locate_named_template_in_inventory(
        client_bgr,
        inv_rect,
        client_rect,
        dest_template,
        template_path=dest_template_path,
        threshold=thr,
    )
    if not dst_matches:
        return None, None, None, None, "dest_not_found"

    src_screen, dst_screen = pick_distinct_screen_points(
        [m.screen_xy for m in src_matches],
        [m.screen_xy for m in dst_matches],
    )
    if src_screen is None or dst_screen is None:
        return None, None, None, None, "dest_not_found"

    src_match = min(
        src_matches,
        key=lambda m: (
            (m.screen_xy[0] - src_screen[0]) ** 2 + (m.screen_xy[1] - src_screen[1]) ** 2,
            m.screen_xy[0],
            m.screen_xy[1],
        ),
    )
    dst_match = min(
        dst_matches,
        key=lambda m: (
            (m.screen_xy[0] - dst_screen[0]) ** 2 + (m.screen_xy[1] - dst_screen[1]) ** 2,
            m.screen_xy[0],
            m.screen_xy[1],
        ),
    )
    src_slot = slot_at_client_point(
        int(src_match.client_xy[0]),
        int(src_match.client_xy[1]),
        inv_rect,
        occupancy=occupancy,
    )
    dst_slot = slot_at_client_point(
        int(dst_match.client_xy[0]),
        int(dst_match.client_xy[1]),
        inv_rect,
        occupancy=occupancy,
    )
    if src_slot is None or dst_slot is None:
        return None, None, None, None, "dest_not_found"
    return src_slot, dst_slot, src_screen, dst_screen, None


def _use_on_label_fail_hint(slot_err: str, dest_id: str) -> str:
    if slot_err == "dest_not_found":
        return (
            "No slot labeled %r in the perception grid (may still be ? or unknown). "
            "Find uses template shape match; use-on tries labels first, then templates."
            % dest_id
        )
    if slot_err == "source_not_found":
        return "No slot with that source item label; trying template match if templates are set."
    return "Could not resolve inventory slots by item label."


def _execute_use_on_screen_clicks(
    arms,
    client_rect: Sequence[int],
    src_screen: Tuple[int, int],
    dst_screen: Tuple[int, int],
) -> None:
    from bot_inventory_actions import clear_inventory_hover

    focus_runelite()
    time.sleep(Env.pre_click_settle_s())
    clear_inventory_hover(client_rect)
    rad = int(os.environ.get("EXODIA_INV_CLICK_RAD", "6"))
    arms.click_at([int(src_screen[0]), int(src_screen[1])], rad=rad)
    time.sleep(Env.use_on_click_gap_s())
    arms.click_at([int(dst_screen[0]), int(dst_screen[1])], rad=rad)


def _use_on_preview_payload(
    eyes,
    inv_rect: Sequence[int],
    client_rect: Sequence[int],
    src: Tuple[int, int],
    dst: Tuple[int, int],
    *,
    source_id: str,
    dest_id: str,
    max_width: Optional[int] = None,
) -> Dict[str, Any]:
    from_center = inventory_slot_client_center(inv_rect, src[0], src[1])
    to_center = inventory_slot_client_center(inv_rect, dst[0], dst[1])
    if from_center is None or to_center is None:
        return {}

    frame_h = frame_w = 0
    if eyes.curr_client is not None and getattr(eyes.curr_client, "size", 0) > 0:
        frame_h, frame_w = eyes.curr_client.shape[:2]
    scale, display_w, display_h = _frame_display_scale(
        int(frame_w), int(frame_h), max_width=max_width
    )

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
    if inv:
        resolved = resolve_inventory_template_path(template, tpl_path)
        if resolved:
            tpl_path = resolved

    snap, stream_err = _refresh_from_stream(client, eyes)
    if stream_err:
        return _fail(stream_err, hint=_stream_fail_hint(stream_err))

    stream_meta = snap.meta if snap is not None else None
    overlay_max_w = _overlay_max_width(stream_meta)
    frame_payload = _frame_meta_payload(snap, eyes, meta=stream_meta)

    matches: List[TemplateMatch] = []
    locate_meta: Dict[str, Any] = {}
    excluded_inv = 0
    err: Optional[str] = None

    if inv:
        perception_source = "stream_cache" if stream_expected() else "live_identify"
        stream_inv_ok = (
            stream_expected()
            and snap is not None
            and stream_snapshot_usable(snap, require_calibrated=True)[0]
        )

        if stream_expected():
            if snap is None:
                return _fail(
                    "stream_frame_unavailable",
                    hint=_stream_fail_hint("stream_frame_unavailable"),
                    **frame_payload,
                )
            if eyes.inventory_rect is None or len(eyes.inventory_rect) != 4:
                if not sync_inventory_geometry_from_snap(eyes, snap):
                    return _fail(
                        "inventory_not_found",
                        hint="stream inventory not calibrated — open inventory or Re-analyze",
                        **frame_payload,
                    )
        else:
            bind_inventory_to_eyes(eyes, refresh_client=False, force=True)
            if eyes.inventory_rect is None or len(eyes.inventory_rect) != 4:
                return _fail(
                    "inventory_not_found",
                    hint="open inventory in RuneLite or recalibrate client_rect.json",
                    **frame_payload,
                )

        if eyes.curr_inventory is None or getattr(eyes.curr_inventory, "size", 0) == 0:
            eyes.check_inventory()
        if eyes.curr_inventory is None or getattr(eyes.curr_inventory, "size", 0) == 0:
            return _fail(
                "no_inventory_crop",
                hint="inventory panel not visible in stream frame",
                **frame_payload,
            )

        from bot_shape_match import inventory_template_threshold

        if eyes.curr_client is None or getattr(eyes.curr_client, "size", 0) == 0:
            return _fail("empty_image", hint="no client frame captured", **frame_payload)
        inv_rect = eyes.inventory_rect
        if inv_rect is None or len(inv_rect) != 4:
            return _fail(
                "inventory_not_found",
                hint="inventory panel not calibrated",
                **frame_payload,
            )

        matches = []
        err: Optional[str] = None
        locate_meta: Dict[str, Any] = {}

        matches, err = locate_named_template_in_inventory(
            eyes.curr_client,
            inv_rect,
            eyes.client_rect,
            template,
            template_path=tpl_path,
            threshold=inventory_template_threshold(),
        )
        locate_meta = {
            "locateMode": "inventory_slots",
            "perception_source": perception_source,
        }

        if not matches and stream_inv_ok and snap is not None:
            cache_matches = _inventory_matches_from_stream_cache(
                eyes, client, snap, template, tpl_path
            )
            if cache_matches:
                matches = cache_matches
                locate_meta = {
                    "locateMode": "stream_cache_slots",
                    "perception_source": "stream_cache",
                }

        if not matches:
            err = err or "template_not_found"
    else:
        if snap is not None and not dry_run:
            from bot_shape_match import shape_match_threshold

            hit = world_hit_for_template(snap.world, template)
            if hit is not None:
                try:
                    score = float(hit.get("score", 0))
                except (TypeError, ValueError):
                    score = 0.0
                if score >= shape_match_threshold():
                    matches = [
                        TemplateMatch(
                            screen_xy=[int(hit["screen_xy"][0]), int(hit["screen_xy"][1])],
                            client_xy=[int(hit["client_xy"][0]), int(hit["client_xy"][1])],
                            score=score,
                        )
                    ]
                    locate_meta = {
                        "locateMode": "stream_cache",
                        "perception_source": "stream_cache",
                    }

        if not matches:
            _sync_playspace_inventory_from_stream(eyes, snap)
            search_roi = playspace_search_roi(eyes)
            if _click_world_cyan_first():
                matches, excluded_inv, err, locate_meta = _locate_world_template_matches(
                    eyes, template, tpl_path
                )
                if not matches and _click_world_playspace_fallback():
                    matches, excluded_inv, err, locate_meta = _locate_world_shape_matches(
                        eyes, template, tpl_path, search_roi
                    )
                    locate_meta["locateMode"] = "shape_fallback"
            else:
                matches, excluded_inv, err, locate_meta = _locate_world_shape_matches(
                    eyes, template, tpl_path, search_roi
                )
            locate_meta.setdefault("perception_source", "live_match")
        else:
            _sync_playspace_inventory_from_stream(eyes, snap)
            matches, excluded_inv = filter_matches_outside_inventory(eyes, matches)
            if not matches:
                err = err or "template_not_found"

    if not matches:
        world_hint = (
            "shape match on item body (crop template to the dark icon, transparent PNG); "
            "playspace excludes inventory — spot: images/osrs_infernalEel.png, item: items/infernal_eel.png"
        )
        inv_hint = "item not in inventory or template does not match live slots"
        return _fail(
            err if err in ("no_inventory_crop", "missing_template", "empty_image") else "template_not_found",
            template=template,
            inv=inv,
            templatePath=tpl_path,
            excludedInventoryMatches=excluded_inv if not inv else None,
            hint=inv_hint if inv else world_hint,
            **frame_payload,
            **locate_meta,
        )

    best = max(matches, key=lambda m: m.score)
    match_count = len(matches)
    slot_label = slot_label_for_match(eyes, best) if inv else None
    click_payload = _click_target_payload(
        client,
        eyes,
        best,
        all_matches=matches,
        max_width=overlay_max_w,
    )

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
            **_merge_action_payload(locate_meta, click_payload, frame_payload),
        )

    if not dry_run:
        snap, stream_meta, frame_payload = _apply_pre_click_stream_refresh(
            client, eyes, snap, stream_meta, frame_payload
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
    time.sleep(Env.pre_click_settle_s())
    arms.click_at(best.screen_xy)

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
        **_merge_action_payload(locate_meta, click_payload, frame_payload),
    )


def _dispatch_use_item_id_on_item_id(
    client,
    eyes,
    arms,
    *,
    source_id: str,
    dest_id: str,
    source_template: Optional[str] = None,
    source_template_path: Optional[str] = None,
    dest_template: Optional[str] = None,
    dest_template_path: Optional[str] = None,
    dry_run: bool,
) -> Dict[str, Any]:
    source_id = (source_id or "").strip()
    dest_id = (dest_id or "").strip()
    if not source_id or not dest_id:
        return _fail("missing_source_or_dest")

    src_tpl = _use_on_template_for_id(source_id, source_template)
    dst_tpl = _use_on_template_for_id(dest_id, dest_template)
    src_tpl_path = (source_template_path or "").strip() or None
    dst_tpl_path = (dest_template_path or "").strip() or None

    snap, stream_err = _refresh_from_stream(client, eyes)
    if stream_err:
        return _fail(stream_err, hint=_stream_fail_hint(stream_err))

    stream_meta = snap.meta if snap is not None else None
    overlay_max_w = _overlay_max_width(stream_meta)
    frame_payload = _frame_meta_payload(snap, eyes, meta=stream_meta)

    perception_source = "live_identify"
    slot_items: Optional[List[List[Optional[str]]]] = None
    occ: Optional[List[List[bool]]] = None

    stream_inv_ok = (
        stream_expected()
        and snap is not None
        and stream_snapshot_usable(snap, require_calibrated=True)[0]
    )
    if stream_inv_ok:
        slot_items, occ = _inventory_grid_from_snap(snap, eyes)
        if slot_items is not None and occ is not None:
            perception_source = "stream_cache"
            snap, frame_payload, slot_items, occ = _poll_stream_inventory_cache(
                client,
                eyes,
                snap,
                source_id=source_id,
                dest_id=dest_id,
            )
            stream_meta = snap.meta

    if slot_items is None or occ is None:
        if stream_expected():
            return _fail(
                "stream_inventory_unavailable",
                hint=_stream_fail_hint("stream_inventory_unavailable"),
                perception_source="stream_cache",
                **frame_payload,
            )
        perception_source = "live_identify"
        inv_rect = bind_inventory_to_eyes(eyes, refresh_client=False, force=True)
        if not inv_rect or len(inv_rect) != 4:
            return _fail(
                "inventory_not_found",
                hint="open inventory in RuneLite",
                **frame_payload,
            )

        client_bgr = eyes.curr_client
        if client_bgr is None or getattr(client_bgr, "size", 0) == 0:
            return _fail("no_client_frame", **frame_payload)

        occ, _count, _proto = inventory_occupancy_from_client(client_bgr, inv_rect)
        if occ is None:
            return _fail("occupancy_failed", **frame_payload)

        slot_items, _, _ = identify_inventory_slot_items(
            client_bgr,
            inv_rect,
            occ,
            frame_buckets=True,
        )
        if slot_items is None:
            return _fail("identify_failed", **frame_payload)
        inv_rect = eyes.inventory_rect
    else:
        if eyes.inventory_rect is None or len(eyes.inventory_rect) != 4:
            if snap is not None:
                sync_inventory_geometry_from_snap(eyes, snap)
        inv_rect = eyes.inventory_rect
        if not inv_rect or len(inv_rect) != 4:
            return _fail(
                "inventory_not_found",
                hint="open inventory in RuneLite",
                perception_source=perception_source,
                **frame_payload,
            )
        if eyes.curr_client is None or getattr(eyes.curr_client, "size", 0) == 0:
            return _fail("no_client_frame", perception_source=perception_source, **frame_payload)

    client_rect = eyes.client_rect or list(client.win_rect)
    client_bgr = eyes.curr_client
    src, dst, slot_err = _resolve_use_on_slots(slot_items, source_id, dest_id)
    resolve_mode = "labels"
    use_screen_clicks = False
    screen_src: Optional[Tuple[int, int]] = None
    screen_dst: Optional[Tuple[int, int]] = None

    if slot_err:
        tpl_src, tpl_dst, tpl_screen_src, tpl_screen_dst, tpl_err = _resolve_use_on_via_templates(
            client_bgr,
            inv_rect,
            client_rect,
            source_template=src_tpl,
            source_template_path=src_tpl_path,
            dest_template=dst_tpl,
            dest_template_path=dst_tpl_path,
            occupancy=occ,
        )
        if tpl_err:
            return _fail(
                slot_err,
                missing_item=source_id if slot_err == "source_not_found" else dest_id,
                sourceId=source_id,
                destId=dest_id,
                source_slot=list(src) if src else None,
                perception_source=perception_source,
                hint=_use_on_label_fail_hint(slot_err, dest_id),
                template_error=tpl_err,
                **frame_payload,
            )
        src, dst = tpl_src, tpl_dst
        screen_src, screen_dst = tpl_screen_src, tpl_screen_dst
        resolve_mode = "template_match"
        use_screen_clicks = True
        perception_source = "template_match"

    preview = _use_on_preview_payload(
        eyes,
        inv_rect,
        client_rect,
        src,
        dst,
        source_id=source_id,
        dest_id=dest_id,
        max_width=overlay_max_w,
    )
    if dry_run:
        src_slots = slots_matching_item(slot_items, source_id)
        dst_slots = slots_matching_item(slot_items, dest_id)
        return _ok(
            dry_run=True,
            sourceSlots=len(src_slots),
            destSlots=len(dst_slots),
            perception_source=perception_source,
            resolveMode=resolve_mode,
            **_merge_action_payload(preview, frame_payload),
        )

    snap, stream_meta, frame_payload = _apply_pre_click_stream_refresh(
        client, eyes, snap, stream_meta, frame_payload
    )
    client_bgr = eyes.curr_client

    if use_screen_clicks and screen_src is not None and screen_dst is not None:
        _execute_use_on_screen_clicks(arms, client_rect, screen_src, screen_dst)
        payload = _merge_action_payload(preview, frame_payload)
        payload["perception_source"] = perception_source
        payload["resolveMode"] = resolve_mode
        payload["source_slot"] = list(src)
        payload["dest_slot"] = list(dst)
        return _ok(**payload)

    result = use_named_item_on_named_item(
        inv_rect,
        client_rect,
        slot_items,
        source_id,
        dest_id,
        arms=arms,
    )
    if not result.ok:
        tpl_src, tpl_dst, tpl_screen_src, tpl_screen_dst, tpl_err = _resolve_use_on_via_templates(
            client_bgr,
            inv_rect,
            client_rect,
            source_template=src_tpl,
            source_template_path=src_tpl_path,
            dest_template=dst_tpl,
            dest_template_path=dst_tpl_path,
            occupancy=occ,
        )
        if tpl_err:
            return _fail(
                result.reason or "use_on_failed",
                missing_item=result.missing_item,
                sourceId=source_id,
                destId=dest_id,
                perception_source=perception_source,
                **frame_payload,
            )
        _execute_use_on_screen_clicks(arms, client_rect, tpl_screen_src, tpl_screen_dst)
        preview = _use_on_preview_payload(
            eyes,
            inv_rect,
            client_rect,
            tpl_src,
            tpl_dst,
            source_id=source_id,
            dest_id=dest_id,
            max_width=overlay_max_w,
        )
        payload = _merge_action_payload(preview, frame_payload)
        payload["perception_source"] = "template_match"
        payload["resolveMode"] = "template_match"
        payload["source_slot"] = list(tpl_src)
        payload["dest_slot"] = list(tpl_dst)
        return _ok(**payload)

    payload = _merge_action_payload(preview, frame_payload)
    payload["perception_source"] = perception_source
    payload["resolveMode"] = resolve_mode
    if result.source_slot:
        payload["source_slot"] = list(result.source_slot)
    if result.dest_slot:
        payload["dest_slot"] = list(result.dest_slot)
    return _ok(**payload)


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
            source_template=str(args.get("sourceTemplate", args.get("source_template", "")) or ""),
            source_template_path=str(
                args.get("sourceTemplatePath", args.get("source_template_path", "")) or ""
            ),
            dest_template=str(args.get("destTemplate", args.get("dest_template", "")) or ""),
            dest_template_path=str(
                args.get("destTemplatePath", args.get("dest_template_path", "")) or ""
            ),
            dry_run=dry_run,
        )

    return _fail("unknown_block", block_id=block_id)
