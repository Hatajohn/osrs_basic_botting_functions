"""
Thin HTTP consumer for the Exodia perception MJPEG stream.

**Latest-frame read contract (action subprocesses):**

1. Call ``refresh_action_frame(client, eyes)`` (or ``fetch_stream_snapshot`` +
   ``apply_stream_snapshot_to_eyes``) at start-of-work.
2. When ``stream_expected()`` is true, use HTTP pristine + ``/meta`` only —
   never ``Actions.bot_update`` / ``capture_frame`` / sync ``wsl_ps`` grab.
3. Process on ``snap.bgr.copy()``; never mutate the stream buffer or bake
   overlays into the base JPEG.
4. On stream failure, return an error — no sync-grab fallback.

``exodia_debug_frame.py`` is recovery-only: blocked when the stream snapshot
is fresh; use ``--force-sync`` for an explicit sync grab when the service is down.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

from bot_capture import (
    StreamFrameMeta,
    capture_stream_enabled,
    fetch_pristine_client_http_meta,
    fetch_stream_meta_http,
    stream_service_port,
)

if TYPE_CHECKING:
    import bot_eyes as Eyes

Rect = List[int]

def configure_action_stream_env() -> None:
    """Action subprocess: prefer HTTP stream, never compete with perception capture."""
    port = stream_service_port()
    if port > 0:
        os.environ.setdefault("EXODIA_CAPTURE_STREAM", "1")
        os.environ.setdefault("EXODIA_STREAM_PORT", str(port))
    # Template match on pristine stream frame (inventory panel must stay visible).
    os.environ.setdefault("EXODIA_MASK_PANELS", "0")


def sync_inventory_geometry_from_snap(eyes: "Eyes.BotEyes", snap: StreamSnapshot) -> bool:
    """Apply cached ``inventory_rect`` from stream meta; no screen grab."""
    if not _valid_rect(snap.inventory_rect):
        return False
    eyes.inventory_rect = [int(v) for v in snap.inventory_rect]
    eyes._sync_inventory_global()
    eyes.check_inventory()
    return True


__all__ = [
    "StreamSnapshot",
    "apply_stream_snapshot_to_eyes",
    "configure_action_stream_env",
    "fetch_stream_snapshot",
    "refresh_action_frame",
    "refresh_stream_snapshot_if_stale",
    "stream_expected",
    "stream_max_frame_age_ms",
    "stream_snapshot_usable",
    "sync_inventory_geometry_from_snap",
    "world_hit_for_template",
]


def _valid_rect(rect: Any) -> bool:
    if rect is None or not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return False
    try:
        w, h = int(rect[2]), int(rect[3])
    except (TypeError, ValueError):
        return False
    return w > 0 and h > 0


def _normalize_template_stem(template: str) -> str:
    stem = (template or "").strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    return stem


def _perception_slices(meta: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    root = meta if isinstance(meta, dict) else {}
    perception = root.get("perception")
    if not isinstance(perception, dict):
        perception = {}
    inventory = perception.get("inventory")
    if not isinstance(inventory, dict):
        inventory = {}
    world = perception.get("world")
    if not isinstance(world, dict):
        world = {}
    return root, inventory, world


def _inventory_rect_from_meta(inventory: Dict[str, Any]) -> Optional[Rect]:
    raw = inventory.get("inventory_rect")
    if not _valid_rect(raw):
        return None
    return [int(raw[i]) for i in range(4)]


@dataclass
class StreamSnapshot:
    """Pristine client frame plus stream ``/meta`` perception slices."""

    bgr: np.ndarray
    frame: StreamFrameMeta
    meta: Dict[str, Any]
    inventory: Dict[str, Any]
    world: Dict[str, Any]
    inventory_rect: Optional[Rect]


def fetch_stream_snapshot(port: Optional[int] = None) -> Optional[StreamSnapshot]:
    """Fetch pristine JPEG + frame meta and top-level ``/meta`` JSON.

    Returns ``None`` when the pristine image or frame sidecar is unavailable.
    """
    bgr, frame = fetch_pristine_client_http_meta(port)
    if bgr is None or frame is None:
        return None
    meta = fetch_stream_meta_http(port) or {}
    _root, inventory, world = _perception_slices(meta)
    inv_rect = _inventory_rect_from_meta(inventory)
    return StreamSnapshot(
        bgr=bgr,
        frame=frame,
        meta=meta,
        inventory=inventory,
        world=world,
        inventory_rect=inv_rect,
    )


def refresh_action_frame(client, eyes) -> Tuple[Optional[StreamSnapshot], Optional[str]]:
    """Sync window geometry, then load the latest action frame (stream or legacy).

    When ``stream_expected()``: ``fetch_stream_snapshot`` only — never
    ``bot_update``. Returns ``(snap, None)`` on success or ``(None, reason)`` on
    stream failure. Legacy mode (no stream) runs ``bot_update`` and returns
    ``(None, None)``.
    """
    import bot_actions as Actions

    Actions.sync_window(client, eyes)
    if not stream_expected():
        Actions.bot_update(client, eyes)
        return None, None
    snap = fetch_stream_snapshot()
    if snap is None:
        return None, "stream_frame_unavailable"
    ok, reason = stream_snapshot_usable(snap, require_calibrated=False)
    if not ok and reason in ("no_snapshot", "no_frame", "no_frame_meta", "frame_stale"):
        return None, reason if reason != "frame_stale" else "stream_meta_stale"
    apply_stream_snapshot_to_eyes(eyes, snap, client_rect=list(client.win_rect))
    return snap, None


def apply_stream_snapshot_to_eyes(
    eyes: "Eyes.BotEyes",
    snap: StreamSnapshot,
    *,
    client_rect: Rect,
) -> None:
    """Apply stream frame and cached perception to ``BotEyes`` (no panel masking)."""
    bgr = np.asarray(snap.bgr, dtype=np.uint8).copy()
    eyes.client_rect = [int(v) for v in client_rect]
    eyes.curr_client = bgr
    eyes.curr_client_unmasked = bgr.copy()

    if _valid_rect(snap.inventory_rect):
        eyes.inventory_rect = [int(v) for v in snap.inventory_rect]
        eyes._sync_inventory_global()
        eyes.check_inventory()
    else:
        eyes.inventory_rect = None
        eyes.inventory_global = None
        eyes.curr_inventory = None

    inv = snap.inventory or {}
    world = snap.world or {}
    inv_rect_local = (
        [int(v) for v in eyes.inventory_rect]
        if eyes.inventory_rect is not None and len(eyes.inventory_rect) == 4
        else None
    )
    h, w = bgr.shape[:2]
    eyes.perception_envelope = {
        "client_rect": list(eyes.client_rect),
        "inventory_rect_client_local": inv_rect_local,
        "inventory_slot_occupancy": inv.get("occupancy"),
        "inventory_slot_items": inv.get("slot_items"),
        "world_hits": [dict(h) for h in (world.get("hits") or []) if isinstance(h, dict)],
        "capture_seq": int(snap.frame.capture_seq),
        "capture_backend": "stream",
        "curr_client_shape_hw": [int(h), int(w)],
        "frame_age_ms": float(snap.frame.frame_age_ms),
        "frame_source": str(snap.frame.source),
    }


def stream_expected() -> bool:
    """True when actions should prefer the MJPEG stream over sync screen grab."""
    return stream_service_port() > 0 or capture_stream_enabled()


def stream_max_frame_age_ms() -> float:
    """Shared stale threshold for ``stream_snapshot_usable`` and pre-click refresh."""
    raw = os.environ.get("EXODIA_MATCH_MAX_FRAME_AGE_MS", "500")
    try:
        return float(raw or "500")
    except (TypeError, ValueError):
        return 500.0


def stream_snapshot_usable(
    snap: Optional[StreamSnapshot],
    *,
    max_age_ms: Optional[float] = None,
    require_calibrated: bool = True,
) -> Tuple[bool, str]:
    """Return ``(ok, reason)`` for using a snapshot in dispatch (fresh + calibrated)."""
    threshold = stream_max_frame_age_ms() if max_age_ms is None else float(max_age_ms)
    if snap is None:
        return False, "no_snapshot"
    if snap.bgr is None or not getattr(snap.bgr, "size", 0):
        return False, "no_frame"
    if snap.frame is None:
        return False, "no_frame_meta"
    if float(snap.frame.frame_age_ms) > threshold:
        return False, "frame_stale"
    if require_calibrated:
        calibrated = bool(snap.inventory.get("inventory_calibrated"))
        if not calibrated and not _valid_rect(snap.inventory_rect):
            return False, "inventory_not_calibrated"
    return True, "ok"


def refresh_stream_snapshot_if_stale(
    client,
    eyes,
    snap: StreamSnapshot,
    *,
    max_age_ms: Optional[float] = None,
) -> StreamSnapshot:
    """Re-fetch pristine client frame when ``snap`` exceeds max age (pre-click freshness)."""
    if snap.frame is None:
        return snap
    threshold = stream_max_frame_age_ms() if max_age_ms is None else float(max_age_ms)
    if float(snap.frame.frame_age_ms) <= threshold:
        return snap
    fresh = fetch_stream_snapshot()
    if fresh is None:
        return snap
    apply_stream_snapshot_to_eyes(eyes, fresh, client_rect=list(client.win_rect))
    return fresh


def world_hit_for_template(world_meta: Dict[str, Any], template: str) -> Optional[Dict[str, Any]]:
    """Best world hit for ``template`` (stem match, highest score) from cache meta."""
    stem = _normalize_template_stem(template)
    if not stem:
        return None
    hits = world_meta.get("hits")
    if not isinstance(hits, list):
        return None
    best: Optional[Dict[str, Any]] = None
    best_score = -1.0
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        name = _normalize_template_stem(str(hit.get("template") or hit.get("name") or ""))
        if name != stem:
            continue
        try:
            score = float(hit.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        if score > best_score:
            best_score = score
            best = dict(hit)
    return best
