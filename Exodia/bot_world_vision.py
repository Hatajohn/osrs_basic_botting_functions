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
from bot_frame_dispatch import FrameQueue
from bot_perception_worker import run_modality_loop
from bot_template_find import TemplateFinder, WorldHitDict
from bot_template_watchlist import WatchlistResolver

Rect = List[int]
WorldTrackDict = Dict[str, Any]


def default_world_vision_fps() -> float:
    raw = os.environ.get("EXODIA_WORLD_VISION_FPS", "10").strip()
    try:
        fps = float(raw)
    except ValueError:
        fps = 10.0
    return max(0.5, min(15.0, fps))


@dataclass(frozen=True)
class WorldPerceptionSnapshot:
    hits: Tuple[WorldHitDict, ...]
    tracks: Tuple[WorldTrackDict, ...]
    templates_scanned: Tuple[str, ...]
    search_roi: Optional[Rect]
    cyan_regions: int
    inventory_filtered: int
    processed_seq: int
    capture_seq: int
    ts: float
    vision_fps: float
    pan_in_progress: bool = False
    motion_magnitude: float = 0.0


@dataclass
class WorldPerceptionCache:
    """Thread-safe world-object locate state for stream consumers."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _hits: List[WorldHitDict] = field(default_factory=list)
    _tracks: List[WorldTrackDict] = field(default_factory=list)
    _templates_scanned: List[str] = field(default_factory=list)
    _search_roi: Optional[Rect] = None
    _cyan_regions: int = 0
    _inventory_filtered: int = 0
    _processed_seq: int = 0
    _capture_seq: int = 0
    _ts: float = 0.0
    _vision_fps: float = 0.0
    _pan_in_progress: bool = False
    _motion_magnitude: float = 0.0

    def update(
        self,
        *,
        hits: List[WorldHitDict],
        tracks: Optional[List[WorldTrackDict]] = None,
        templates_scanned: Sequence[str],
        search_roi: Optional[Rect],
        cyan_regions: int,
        inventory_filtered: int,
        processed_seq: int,
        capture_seq: int,
        vision_fps: float,
        pan_in_progress: bool = False,
        motion_magnitude: float = 0.0,
    ) -> None:
        with self._lock:
            self._hits = [dict(h) for h in hits]
            self._tracks = [dict(t) for t in (tracks or [])]
            self._templates_scanned = [str(t) for t in templates_scanned]
            self._search_roi = list(search_roi) if search_roi else None
            self._cyan_regions = int(cyan_regions)
            self._inventory_filtered = int(inventory_filtered)
            self._processed_seq = int(processed_seq)
            self._capture_seq = int(capture_seq)
            self._ts = time.monotonic()
            self._vision_fps = float(vision_fps)
            self._pan_in_progress = bool(pan_in_progress)
            self._motion_magnitude = float(motion_magnitude)

    def snapshot(self) -> WorldPerceptionSnapshot:
        with self._lock:
            return WorldPerceptionSnapshot(
                hits=tuple(dict(h) for h in self._hits),
                tracks=tuple(dict(t) for t in self._tracks),
                templates_scanned=tuple(self._templates_scanned),
                search_roi=list(self._search_roi) if self._search_roi else None,
                cyan_regions=self._cyan_regions,
                inventory_filtered=self._inventory_filtered,
                processed_seq=self._processed_seq,
                capture_seq=self._capture_seq,
                ts=self._ts,
                vision_fps=self._vision_fps,
                pan_in_progress=self._pan_in_progress,
                motion_magnitude=self._motion_magnitude,
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
            "tracks": [dict(t) for t in snap.tracks],
            "hit_count": len(snap.hits),
            "track_count": len(snap.tracks),
            "templates_scanned": list(snap.templates_scanned),
            "template_stats": template_stats,
            "search_roi": list(snap.search_roi) if snap.search_roi else None,
            "cyan_regions": snap.cyan_regions,
            "inventory_filtered": snap.inventory_filtered,
            "processed_seq": snap.processed_seq,
            "capture_seq": snap.capture_seq,
            "vision_fps": round(snap.vision_fps, 2),
            "pan_in_progress": snap.pan_in_progress,
            "motion_magnitude": round(snap.motion_magnitude, 2),
        }


class WorldVisionProcessor:
    """Daemon thread: world template locate at capture rate, parallel to inventory."""

    def __init__(
        self,
        buffer: FrameBuffer,
        inv_cache: Any,
        world_cache: WorldPerceptionCache,
        client_rect: Rect,
        *,
        frame_queue: Optional[FrameQueue] = None,
        fps: Optional[float] = None,
        control_file: Optional[Path] = None,
    ) -> None:
        self._buffer = buffer
        self._frame_queue = frame_queue
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
        self._prev_frame_bgr: Optional[Any] = None
        from bot_world_track import WorldObjectTrackerState

        self._tracker_state = WorldObjectTrackerState()

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    def _capture_seq(self, snap: FrameSnapshot) -> int:
        return snap.seq if self._frame_queue is not None else self._buffer.seq

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
        self._watchlist.refresh()
        inv_snap = self._inv_cache.snapshot()
        inventory_rect = inv_snap.inventory_rect
        template_names = self._watchlist.world_template_names()
        client_bgr = snap.bgr
        if client_bgr is None or not getattr(client_bgr, "size", 0):
            return

        hits, search_roi, cyan_count, inv_filtered = TemplateFinder.locate_world(
            snap,
            template_names,
            inventory_rect,
            self._client_rect,
        )

        h0, w0 = client_bgr.shape[:2]

        from bot_stream_control import read_pan_in_progress
        from bot_world_track import playspace_motion_magnitude, tracks_to_dict, update_world_tracks

        control_pan = read_pan_in_progress(self._control_file)
        motion_mag = playspace_motion_magnitude(
            self._prev_frame_bgr,
            client_bgr,
            inventory_rect=inventory_rect,
        )
        self._prev_frame_bgr = client_bgr.copy()

        tracks = update_world_tracks(
            self._tracker_state,
            hits,
            ts=time.monotonic(),
            client_w=w0,
            vision_fps=self._actual_fps if self._actual_fps > 0 else self._fps,
            frame_bgr=client_bgr,
            control_pan=control_pan,
            motion_magnitude=motion_mag,
        )
        track_dicts = tracks_to_dict(tracks)

        self._cache.update(
            hits=hits,
            tracks=track_dicts,
            templates_scanned=template_names,
            search_roi=search_roi,
            cyan_regions=cyan_count,
            inventory_filtered=inv_filtered,
            processed_seq=snap.seq,
            capture_seq=self._capture_seq(snap),
            vision_fps=self._actual_fps,
            pan_in_progress=self._tracker_state.pan_in_progress,
            motion_magnitude=motion_mag,
        )

    def _run_vision(self) -> None:
        def _process(snap: FrameSnapshot) -> None:
            self._watchlist.refresh()
            self._process_frame(snap)

        run_modality_loop(
            frame_queue=self._frame_queue,
            buffer=self._buffer,
            stop_event=self._stop,
            fps=self._fps,
            process_fn=_process,
            idle_wait_s=0.05,
            on_fps=lambda fps: setattr(self, "_actual_fps", fps),
        )


__all__ = [
    "WorldPerceptionCache",
    "WorldPerceptionSnapshot",
    "WorldVisionProcessor",
    "WorldTrackDict",
    "default_world_vision_fps",
]
