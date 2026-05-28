"""
Incremental world-object perception for the live MJPEG stream.

``WorldVisionProcessor`` runs in parallel with ``InventoryVisionProcessor`` on
its own daemon thread. It never blocks on inventory work — only lock-free
``inv_cache.snapshot()`` for ``inventory_rect`` filtering.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot_capture import FrameBuffer, FrameSnapshot
from bot_template_watchlist import WatchlistResolver

Rect = List[int]
WorldHitDict = Dict[str, Any]


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def default_world_vision_fps() -> float:
    raw = os.environ.get("EXODIA_WORLD_VISION_FPS", "2").strip()
    try:
        fps = float(raw)
    except ValueError:
        fps = 2.0
    return max(0.5, min(15.0, fps))


def _world_cyan_first_for_vision() -> bool:
    """Shape match by default; cyan path only when ``EXODIA_WORLD_CYAN_FIRST=1``."""
    return _env_bool("EXODIA_WORLD_CYAN_FIRST", False)


def _match_to_hit_dict(match: Any, template: str) -> WorldHitDict:
    return {
        "template": template,
        "client_xy": [int(match.client_xy[0]), int(match.client_xy[1])],
        "screen_xy": [int(match.screen_xy[0]), int(match.screen_xy[1])],
        "score": round(float(match.score), 4),
    }


def _hit_dict_from_world_object(hit: Any) -> WorldHitDict:
    return {
        "template": hit.name,
        "client_xy": hit.client_xy[:],
        "screen_xy": hit.screen_xy[:],
        "score": round(float(hit.score), 4),
    }


def _ensure_bot_eyes(
    client_bgr: np.ndarray,
    client_rect: Rect,
    inventory_rect: Optional[Rect],
) -> Any:
    import bot_eyes as EyesMod

    bot_e = EyesMod.BotEyes()
    h0, w0 = client_bgr.shape[:2]
    bot_e.setRect([0, 0, w0, h0], refresh=False)
    bot_e.client_rect = [int(v) for v in client_rect]
    bot_e.curr_client = client_bgr
    bot_e.curr_client_unmasked = client_bgr
    if inventory_rect is not None and len(inventory_rect) == 4:
        bot_e.inventory_rect = [int(v) for v in inventory_rect]
    return bot_e


def _locate_shape_matches(
    client_bgr: np.ndarray,
    client_rect: Rect,
    inventory_rect: Optional[Rect],
    template_names: Sequence[str],
    search_roi: Optional[Rect],
) -> Tuple[List[WorldHitDict], int]:
    """Playspace shape match aligned with ``bot_chain._locate_world_shape_matches``."""
    from bot_shape_match import shape_match_threshold, shape_preprocess_playspace
    from bot_world_objects import filter_matches_outside_rect, resolve_world_template_file

    bot_e = _ensure_bot_eyes(client_bgr, client_rect, inventory_rect)
    hits: List[WorldHitDict] = []
    inventory_filtered = 0
    use_shape = shape_preprocess_playspace()
    threshold = shape_match_threshold()

    for name in template_names:
        stem, tpl_path = resolve_world_template_file(name)
        if not tpl_path:
            continue
        detailed = bot_e.locate_image_detailed(
            inv=False,
            filename=stem,
            threshold=threshold,
            name="World object (shape)",
            search_roi=search_roi,
            template_path=tpl_path,
            frame_bgr=client_bgr,
            shape_preprocess=use_shape,
            shape_playspace=True,
        )
        matches = list(detailed.matches) if detailed.found else []
        filtered, dropped = filter_matches_outside_rect(matches, inventory_rect)
        inventory_filtered += dropped
        for match in filtered:
            hits.append(_match_to_hit_dict(match, stem))

    return hits, inventory_filtered


def _locate_cyan_matches(
    client_bgr: np.ndarray,
    inventory_rect: Optional[Rect],
    template_names: Sequence[str],
) -> Tuple[List[WorldHitDict], Optional[Rect], int, int]:
    from bot_world_objects import locate_world_objects

    result = locate_world_objects(
        client_bgr,
        template_names,
        inventory_rect=inventory_rect,
    )
    hits = [_hit_dict_from_world_object(h) for h in result.hits]
    cyan_count = len(result.cyan_regions)
    inv_filtered = result.inventory_filtered + result.cyan_rejected
    return hits, result.search_roi, cyan_count, inv_filtered


@dataclass(frozen=True)
class WorldPerceptionSnapshot:
    hits: Tuple[WorldHitDict, ...]
    templates_scanned: Tuple[str, ...]
    search_roi: Optional[Rect]
    cyan_regions: int
    inventory_filtered: int
    processed_seq: int
    capture_seq: int
    ts: float
    vision_fps: float


@dataclass
class WorldPerceptionCache:
    """Thread-safe world-object locate state for stream consumers."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _hits: List[WorldHitDict] = field(default_factory=list)
    _templates_scanned: List[str] = field(default_factory=list)
    _search_roi: Optional[Rect] = None
    _cyan_regions: int = 0
    _inventory_filtered: int = 0
    _processed_seq: int = 0
    _capture_seq: int = 0
    _ts: float = 0.0
    _vision_fps: float = 0.0

    def update(
        self,
        *,
        hits: List[WorldHitDict],
        templates_scanned: Sequence[str],
        search_roi: Optional[Rect],
        cyan_regions: int,
        inventory_filtered: int,
        processed_seq: int,
        capture_seq: int,
        vision_fps: float,
    ) -> None:
        with self._lock:
            self._hits = [dict(h) for h in hits]
            self._templates_scanned = [str(t) for t in templates_scanned]
            self._search_roi = list(search_roi) if search_roi else None
            self._cyan_regions = int(cyan_regions)
            self._inventory_filtered = int(inventory_filtered)
            self._processed_seq = int(processed_seq)
            self._capture_seq = int(capture_seq)
            self._ts = time.monotonic()
            self._vision_fps = float(vision_fps)

    def snapshot(self) -> WorldPerceptionSnapshot:
        with self._lock:
            return WorldPerceptionSnapshot(
                hits=tuple(dict(h) for h in self._hits),
                templates_scanned=tuple(self._templates_scanned),
                search_roi=list(self._search_roi) if self._search_roi else None,
                cyan_regions=self._cyan_regions,
                inventory_filtered=self._inventory_filtered,
                processed_seq=self._processed_seq,
                capture_seq=self._capture_seq,
                ts=self._ts,
                vision_fps=self._vision_fps,
            )

    def world_meta(self) -> Dict[str, Any]:
        snap = self.snapshot()
        hit_counts: Dict[str, int] = {}
        best_scores: Dict[str, float] = {}
        for h in snap.hits:
            t = str(h.get("template", ""))
            if not t:
                continue
            hit_counts[t] = hit_counts.get(t, 0) + 1
            score = float(h.get("score", 0.0))
            best_scores[t] = max(best_scores.get(t, 0.0), score)
        template_stats = [
            {
                "template": t,
                "hits": hit_counts.get(t, 0),
                "best_score": round(best_scores[t], 4) if t in best_scores else None,
            }
            for t in snap.templates_scanned
        ]
        return {
            "hits": [dict(h) for h in snap.hits],
            "hit_count": len(snap.hits),
            "templates_scanned": list(snap.templates_scanned),
            "template_stats": template_stats,
            "search_roi": list(snap.search_roi) if snap.search_roi else None,
            "cyan_regions": snap.cyan_regions,
            "inventory_filtered": snap.inventory_filtered,
            "processed_seq": snap.processed_seq,
            "capture_seq": snap.capture_seq,
            "vision_fps": round(snap.vision_fps, 2),
        }


class WorldVisionProcessor:
    """Daemon thread: world template locate at low FPS, parallel to inventory."""

    def __init__(
        self,
        buffer: FrameBuffer,
        inv_cache: Any,
        world_cache: WorldPerceptionCache,
        client_rect: Rect,
        *,
        fps: Optional[float] = None,
        control_file: Optional[Path] = None,
    ) -> None:
        self._buffer = buffer
        self._inv_cache = inv_cache
        self._cache = world_cache
        self._client_rect = [int(v) for v in client_rect]
        self._fps = fps if fps is not None else default_world_vision_fps()
        self._control_file = control_file
        self._watchlist = WatchlistResolver(control_file=control_file)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_processed_seq = 0
        self._actual_fps = 0.0

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_vision, name="WorldVisionProcessor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _process_frame(self, snap: FrameSnapshot) -> None:
        from bot_search import playspace_search_roi

        self._watchlist.refresh()
        inv_snap = self._inv_cache.snapshot()
        inventory_rect = inv_snap.inventory_rect
        template_names = self._watchlist.world_template_names()
        client_bgr = snap.bgr
        if client_bgr is None or not getattr(client_bgr, "size", 0):
            return

        h0, w0 = client_bgr.shape[:2]
        search_roi = playspace_search_roi(
            w0,
            h0,
            inventory_rect=inventory_rect,
        )

        if _world_cyan_first_for_vision():
            hits, search_roi, cyan_count, inv_filtered = _locate_cyan_matches(
                client_bgr,
                inventory_rect,
                template_names,
            )
        else:
            hits, inv_filtered = _locate_shape_matches(
                client_bgr,
                self._client_rect,
                inventory_rect,
                template_names,
                search_roi,
            )
            cyan_count = 0

        self._cache.update(
            hits=hits,
            templates_scanned=template_names,
            search_roi=search_roi,
            cyan_regions=cyan_count,
            inventory_filtered=inv_filtered,
            processed_seq=snap.seq,
            capture_seq=self._buffer.seq,
            vision_fps=self._actual_fps,
        )

    def _run_vision(self) -> None:
        processed = 0
        t0 = time.monotonic()
        min_interval = 1.0 / self._fps if self._fps > 0 else 0.0

        while not self._stop.is_set():
            self._watchlist.refresh()
            snap = self._buffer.latest_copy()
            if snap is None or snap.seq <= self._last_processed_seq:
                self._stop.wait(0.05)
                continue

            if snap.seq > self._last_processed_seq + 1:
                fresh = self._buffer.latest_copy()
                if fresh is not None:
                    snap = fresh

            try:
                self._process_frame(snap)
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
    "WorldPerceptionCache",
    "WorldPerceptionSnapshot",
    "WorldVisionProcessor",
    "default_world_vision_fps",
]
