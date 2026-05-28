"""
Incremental inventory perception for the live MJPEG stream.

``InventoryVisionProcessor`` runs a **fast loop** (occupancy + cache state at
stream rate) and a **background identify worker** (template match in small
batches). Overlay JPEGs are composited in ``PerceptionStreamPublisher`` from
the live capture buffer + cache, so re-analyze never blocks the game view.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_capture import FrameBuffer, FrameSnapshot
from bot_eyes import INV_COLS, INV_ROWS
from bot_template_watchlist import WatchlistResolver, locate_inventory_watch_templates

Rect = List[int]
SlotCoord = Tuple[int, int]

_UNKNOWN_LABEL = "?"


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def default_inventory_vision_fps() -> float:
    raw = os.environ.get("EXODIA_INVENTORY_VISION_FPS", "10").strip()
    try:
        fps = float(raw)
    except ValueError:
        fps = 10.0
    return max(1.0, min(30.0, fps))


def _empty_occupancy() -> List[List[bool]]:
    return [[False] * INV_COLS for _ in range(INV_ROWS)]


def _empty_slot_grid() -> List[List[Optional[str]]]:
    return [[None] * INV_COLS for _ in range(INV_ROWS)]


def _count_slot_stats(
    occupancy: Sequence[Sequence[bool]],
    slot_items: Sequence[Sequence[Optional[str]]],
) -> Dict[str, int]:
    from bot_inventory_items import is_frame_bucket_label

    occupied = sum(1 for row in occupancy for cell in row if cell)
    unknown = 0
    tmp_count = 0
    for row in range(len(occupancy)):
        for col in range(len(occupancy[row])):
            if not occupancy[row][col]:
                continue
            if row >= len(slot_items) or col >= len(slot_items[row]):
                continue
            label = slot_items[row][col]
            if label == _UNKNOWN_LABEL:
                unknown += 1
            elif label is not None and is_frame_bucket_label(label):
                tmp_count += 1
    return {"occupied": occupied, "unknown": unknown, "tmp_count": tmp_count}


def compute_dirty_slots(
    old_occ: Optional[Sequence[Sequence[bool]]],
    new_occ: Sequence[Sequence[bool]],
    slot_items: Optional[Sequence[Sequence[Optional[str]]]],
    *,
    force_all: bool = False,
) -> List[SlotCoord]:
    """Return slot coordinates that need re-identify on this frame."""
    dirty: List[SlotCoord] = []
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            old = (
                bool(old_occ[row][col])
                if old_occ is not None and row < len(old_occ) and col < len(old_occ[row])
                else False
            )
            new = (
                bool(new_occ[row][col])
                if row < len(new_occ) and col < len(new_occ[row])
                else False
            )
            if force_all and new:
                dirty.append((row, col))
                continue
            if old != new:
                dirty.append((row, col))
                continue
            if new:
                label: Optional[str] = None
                if slot_items is not None and row < len(slot_items) and col < len(slot_items[row]):
                    label = slot_items[row][col]
                if label is None or label == _UNKNOWN_LABEL:
                    dirty.append((row, col))
    return dirty


@dataclass(frozen=True)
class InventoryPerceptionSnapshot:
    inventory_rect: Optional[Rect]
    outline_score: float
    occupancy: Tuple[Tuple[bool, ...], ...]
    slot_items: Tuple[Tuple[Optional[str], ...], ...]
    occupied: int
    unknown: int
    tmp_count: int
    inventory_calibrated: bool
    processed_seq: int
    capture_seq: int
    ts: float
    vision_fps: float
    dirty_slots: Tuple[SlotCoord, ...]
    reidentify_pending: int


@dataclass
class InventoryPerceptionCache:
    """Thread-safe incremental inventory state for stream consumers."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _inventory_rect: Optional[Rect] = None
    _outline_score: float = 0.0
    _occupancy: List[List[bool]] = field(default_factory=_empty_occupancy)
    _slot_items: List[List[Optional[str]]] = field(default_factory=_empty_slot_grid)
    _overlay_jpeg: Optional[bytes] = None
    _processed_seq: int = 0
    _capture_seq: int = 0
    _ts: float = 0.0
    _vision_fps: float = 0.0
    _dirty_slots: Tuple[SlotCoord, ...] = ()
    _reidentify_pending: int = 0
    _force_invalidate: bool = False
    _inventory_watch: List[Dict[str, Any]] = field(default_factory=list)

    def request_invalidate(self) -> None:
        with self._lock:
            self._force_invalidate = True

    def consume_invalidate(self) -> bool:
        with self._lock:
            if not self._force_invalidate:
                return False
            self._force_invalidate = False
            return True

    def update(
        self,
        *,
        inventory_rect: Optional[Rect],
        outline_score: float,
        occupancy: List[List[bool]],
        slot_items: List[List[Optional[str]]],
        processed_seq: int,
        capture_seq: int,
        vision_fps: float,
        dirty_slots: Sequence[SlotCoord] = (),
        reidentify_pending: int = 0,
        overlay_jpeg: Optional[bytes] = None,
    ) -> None:
        with self._lock:
            self._inventory_rect = list(inventory_rect) if inventory_rect else None
            self._outline_score = float(outline_score)
            self._occupancy = [list(row) for row in occupancy]
            self._slot_items = [list(row) for row in slot_items]
            self._processed_seq = int(processed_seq)
            self._capture_seq = int(capture_seq)
            self._ts = time.monotonic()
            self._vision_fps = float(vision_fps)
            self._dirty_slots = tuple(dirty_slots)
            self._reidentify_pending = int(reidentify_pending)
            if overlay_jpeg is not None:
                self._overlay_jpeg = overlay_jpeg

    def update_labels(
        self,
        slot_items: List[List[Optional[str]]],
        *,
        reidentify_pending: int,
    ) -> None:
        with self._lock:
            self._slot_items = [list(row) for row in slot_items]
            self._reidentify_pending = int(reidentify_pending)
            self._ts = time.monotonic()

    def set_inventory_watch(self, matches: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._inventory_watch = [dict(m) for m in matches]

    def overlay_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._overlay_jpeg

    def snapshot(self) -> InventoryPerceptionSnapshot:
        with self._lock:
            inv = list(self._inventory_rect) if self._inventory_rect else None
            occ = tuple(tuple(row) for row in self._occupancy)
            items = tuple(tuple(row) for row in self._slot_items)
            stats = _count_slot_stats(self._occupancy, self._slot_items)
            return InventoryPerceptionSnapshot(
                inventory_rect=inv,
                outline_score=self._outline_score,
                occupancy=occ,
                slot_items=items,
                occupied=stats["occupied"],
                unknown=stats["unknown"],
                tmp_count=stats["tmp_count"],
                inventory_calibrated=inv is not None and len(inv) == 4,
                processed_seq=self._processed_seq,
                capture_seq=self._capture_seq,
                ts=self._ts,
                vision_fps=self._vision_fps,
                dirty_slots=self._dirty_slots,
                reidentify_pending=self._reidentify_pending,
            )

    def inventory_meta(self) -> Dict[str, Any]:
        snap = self.snapshot()
        with self._lock:
            inventory_watch = [dict(m) for m in self._inventory_watch]
        template_stats = [
            {
                "template": str(entry.get("template", "")),
                "slots": len(entry.get("slots") or []),
                "best_score": entry.get("best_score"),
                "source": entry.get("source"),
            }
            for entry in inventory_watch
        ]
        return {
            "occupied": snap.occupied,
            "unknown": snap.unknown,
            "tmp_count": snap.tmp_count,
            "inventory_calibrated": snap.inventory_calibrated,
            "outline_score": round(snap.outline_score, 4),
            "processed_seq": snap.processed_seq,
            "capture_seq": snap.capture_seq,
            "vision_fps": round(snap.vision_fps, 2),
            "dirty_slots": [list(s) for s in snap.dirty_slots],
            "reidentify_pending": snap.reidentify_pending,
            "inventory_rect": list(snap.inventory_rect) if snap.inventory_rect else None,
            "occupancy": [list(row) for row in snap.occupancy],
            "slot_items": [list(row) for row in snap.slot_items],
            "inventory_watch": inventory_watch,
            "inventory_template_stats": template_stats,
        }

    def perception_meta(self) -> Dict[str, Any]:
        """Inventory perception meta (alias for ``inventory_meta``)."""
        return self.inventory_meta()


class InventoryVisionProcessor:
    """Fast occupancy loop + background identify worker (never blocks stream)."""

    def __init__(
        self,
        buffer: FrameBuffer,
        cache: InventoryPerceptionCache,
        *,
        fps: Optional[float] = None,
        max_overlay_width: int = 640,
        outline_rematch_s: Optional[float] = None,
        control_file: Optional[Path] = None,
    ) -> None:
        self._buffer = buffer
        self._cache = cache
        self._fps = fps if fps is not None else default_inventory_vision_fps()
        self._max_overlay_width = max(320, int(max_overlay_width))
        self._outline_rematch_s = (
            outline_rematch_s
            if outline_rematch_s is not None
            else _env_float("EXODIA_INV_OUTLINE_REMATCH_S", 30.0)
        )
        self._control_file = control_file
        self._watchlist = WatchlistResolver(control_file=control_file)
        self._stop = threading.Event()
        self._vision_thread: Optional[threading.Thread] = None
        self._identify_thread: Optional[threading.Thread] = None
        self._last_processed_seq = 0
        self._actual_fps = 0.0
        self._inventory_rect: Optional[Rect] = None
        self._outline_score = 0.0
        self._occupancy = _empty_occupancy()
        self._slot_items = _empty_slot_grid()
        self._last_outline_match = 0.0
        self._outline_min_score = _env_float("EXODIA_INV_OUTLINE_THR", 0.55)
        self._identify_queue: Deque[SlotCoord] = deque()
        self._queue_lock = threading.Lock()
        self._slot_lock = threading.Lock()
        self._identify_snap_lock = threading.Lock()
        self._identify_snap: Optional[FrameSnapshot] = None
        self._identify_batch = max(
            1, int(_env_float("EXODIA_INV_IDENTIFY_BATCH", 2))
        )

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    def request_invalidate(self) -> None:
        self._cache.request_invalidate()

    def start(self) -> None:
        if self._vision_thread is not None:
            return
        self._stop.clear()
        self._vision_thread = threading.Thread(
            target=self._run_vision, name="InventoryVisionProcessor", daemon=True
        )
        self._identify_thread = threading.Thread(
            target=self._run_identify, name="InventoryIdentifyWorker", daemon=True
        )
        self._vision_thread.start()
        self._identify_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in (self._vision_thread, self._identify_thread):
            if thread is not None:
                thread.join(timeout=5.0)
        self._vision_thread = None
        self._identify_thread = None

    def _pending_identify_count(self) -> int:
        with self._queue_lock:
            return len(self._identify_queue)

    def _enqueue_identify(self, slots: Sequence[SlotCoord]) -> None:
        if not slots:
            return
        with self._queue_lock:
            seen = set(self._identify_queue)
            for slot in slots:
                if slot not in seen:
                    self._identify_queue.append(slot)
                    seen.add(slot)

    def _enqueue_all_occupied(self, occ: Sequence[Sequence[bool]]) -> None:
        slots = [
            (row, col)
            for row in range(INV_ROWS)
            for col in range(INV_COLS)
            if row < len(occ) and col < len(occ[row]) and occ[row][col]
        ]
        with self._queue_lock:
            self._identify_queue.clear()
            self._identify_queue.extend(slots)

    def _dequeue_identify_batch(self) -> List[SlotCoord]:
        with self._queue_lock:
            batch: List[SlotCoord] = []
            while self._identify_queue and len(batch) < self._identify_batch:
                batch.append(self._identify_queue.popleft())
            return batch

    def _poll_control_file(self) -> None:
        path = self._control_file
        if path is None or not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("invalidate"):
                self._cache.request_invalidate()
                data["invalidate"] = False
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    def _ensure_inventory_rect(self, snap: FrameSnapshot) -> Optional[Rect]:
        from bot_inventory_detect import match_inventory_by_outline

        now = time.monotonic()
        need_match = (
            self._inventory_rect is None
            or self._outline_score < self._outline_min_score
            or (now - self._last_outline_match) >= self._outline_rematch_s
        )
        if not need_match:
            return self._inventory_rect

        matched = match_inventory_by_outline(snap.bgr)
        if matched is None:
            return self._inventory_rect
        rect, score = matched
        self._inventory_rect = [int(v) for v in rect]
        self._outline_score = float(score)
        self._last_outline_match = now
        return self._inventory_rect

    def _process_frame_fast(self, snap: FrameSnapshot) -> None:
        """Occupancy + cache only — identify runs on the worker thread."""
        from bot_inventory_detect import inventory_occupancy_from_client

        inv_rect = self._ensure_inventory_rect(snap)
        force_reanalyze = self._cache.consume_invalidate()

        with self._identify_snap_lock:
            self._identify_snap = snap

        if inv_rect is None:
            self._cache.update(
                inventory_rect=None,
                outline_score=self._outline_score,
                occupancy=_empty_occupancy(),
                slot_items=_empty_slot_grid(),
                processed_seq=snap.seq,
                capture_seq=self._buffer.seq,
                vision_fps=self._actual_fps,
                reidentify_pending=self._pending_identify_count(),
            )
            return

        occ, _count, _proto = inventory_occupancy_from_client(snap.bgr, inv_rect)
        if occ is None:
            occ = _empty_occupancy()

        dirty = compute_dirty_slots(self._occupancy, occ, self._slot_items, force_all=False)
        if force_reanalyze:
            self._enqueue_all_occupied(occ)
        elif dirty:
            self._enqueue_identify(dirty)

        with self._slot_lock:
            for row in range(INV_ROWS):
                for col in range(INV_COLS):
                    if not occ[row][col]:
                        self._slot_items[row][col] = None
            self._occupancy = [list(row) for row in occ]
            items_snapshot = [list(row) for row in self._slot_items]

        self._cache.update(
            inventory_rect=inv_rect,
            outline_score=self._outline_score,
            occupancy=self._occupancy,
            slot_items=items_snapshot,
            processed_seq=snap.seq,
            capture_seq=self._buffer.seq,
            vision_fps=self._actual_fps,
            dirty_slots=dirty,
            reidentify_pending=self._pending_identify_count(),
        )

        self._watchlist.refresh()
        inv_templates = self._watchlist.inventory_template_names()
        if inv_templates:
            watch_matches = locate_inventory_watch_templates(
                snap.bgr,
                inv_rect,
                snap.client_rect,
                inv_templates,
                slot_items=items_snapshot,
            )
            self._cache.set_inventory_watch(watch_matches)
        else:
            self._cache.set_inventory_watch([])

    def _run_frame_buckets_if_idle(self) -> None:
        if self._pending_identify_count() > 0:
            return
        from bot_inventory_items import apply_frame_fingerprint_buckets

        with self._identify_snap_lock:
            snap = self._identify_snap
        inv_rect = self._inventory_rect
        if snap is None or inv_rect is None:
            return

        with self._slot_lock:
            grid, _buckets = apply_frame_fingerprint_buckets(
                snap.bgr,
                inv_rect,
                self._occupancy,
                self._slot_items,
            )
            self._slot_items = [list(row) for row in grid]
            items_snapshot = [list(row) for row in self._slot_items]

        self._cache.update_labels(
            items_snapshot,
            reidentify_pending=0,
        )

    def _run_identify(self) -> None:
        from bot_inventory_items import identify_inventory_slots_dirty

        while not self._stop.is_set():
            batch = self._dequeue_identify_batch()
            if not batch:
                self._run_frame_buckets_if_idle()
                self._stop.wait(0.02)
                continue

            with self._identify_snap_lock:
                snap = self._identify_snap
            inv_rect = self._inventory_rect
            if snap is None or inv_rect is None:
                self._stop.wait(0.02)
                continue

            with self._slot_lock:
                self._slot_items, _scores = identify_inventory_slots_dirty(
                    snap.bgr,
                    inv_rect,
                    self._occupancy,
                    self._slot_items,
                    batch,
                    frame_buckets=False,
                )
                items_snapshot = [list(row) for row in self._slot_items]

            pending = self._pending_identify_count()
            self._cache.update_labels(items_snapshot, reidentify_pending=pending)
            if pending == 0:
                self._run_frame_buckets_if_idle()

    def _run_vision(self) -> None:
        processed = 0
        t0 = time.monotonic()
        min_interval = 1.0 / self._fps if self._fps > 0 else 0.0

        while not self._stop.is_set():
            self._poll_control_file()
            snap = self._buffer.latest_copy()
            if snap is None or snap.seq <= self._last_processed_seq:
                self._stop.wait(0.01)
                continue

            if snap.seq > self._last_processed_seq + 1:
                fresh = self._buffer.latest_copy()
                if fresh is not None:
                    snap = fresh

            try:
                self._process_frame_fast(snap)
            except Exception:
                pass

            self._last_processed_seq = snap.seq
            processed += 1
            elapsed = time.monotonic() - t0
            if elapsed >= 1.0:
                self._actual_fps = processed / elapsed
                processed = 0
                t0 = time.monotonic()

            if min_interval > 0:
                self._stop.wait(min_interval)


__all__ = [
    "InventoryPerceptionCache",
    "InventoryPerceptionSnapshot",
    "InventoryVisionProcessor",
    "compute_dirty_slots",
    "default_inventory_vision_fps",
]
