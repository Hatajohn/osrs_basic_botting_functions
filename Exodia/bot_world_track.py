"""
Temporal world-object tracking on template detections (Phase 0b).

Associates per-frame ``WorldHit`` dicts from ``WorldVisionProcessor`` into
persistent ``track_id``s with velocity and stability flags for ``/meta`` consumers.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import distance as dist

from bot_track import scaled_max_distance

WorldHitDict = Dict[str, Any]
WorldTrackDict = Dict[str, Any]

__all__ = [
    "WorldObjectTrack",
    "WorldObjectTrackerConfig",
    "WorldObjectTrackerState",
    "default_world_tracker_config",
    "tracks_to_dict",
    "update_world_tracks",
]


@dataclass(frozen=True)
class WorldObjectTrack:
    track_id: int
    template: str
    client_xy: Tuple[int, int]
    screen_xy: Tuple[int, int]
    velocity_xy: Tuple[float, float]
    score: float
    age_frames: int
    missed_frames: int
    stable: bool


@dataclass(frozen=True)
class WorldObjectTrackerConfig:
    max_distance: float = 50.0
    max_missed: int = 4
    stable_min_frames: int = 5
    stable_variance_threshold: float = 64.0
    velocity_history: int = 3
    extrapolate_on_miss: bool = True


def default_world_tracker_config(
    client_w: int,
    *,
    vision_fps: float = 10.0,
) -> WorldObjectTrackerConfig:
    return WorldObjectTrackerConfig(
        max_distance=scaled_max_distance(client_w),
        max_missed=max(2, int(round(vision_fps * 0.5))),
    )


@dataclass
class _InternalTrack:
    track_id: int
    template: str
    client_xy: Tuple[int, int]
    screen_xy: Tuple[int, int]
    velocity_xy: Tuple[float, float] = (0.0, 0.0)
    score: float = 0.0
    age_frames: int = 0
    missed_frames: int = 0
    stable: bool = False
    positions: Deque[Tuple[int, int]] = field(default_factory=lambda: deque(maxlen=8))
    timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=8))


@dataclass
class WorldObjectTrackerState:
    """Mutable tracker state owned by ``WorldVisionProcessor``."""

    tracks: Dict[int, _InternalTrack] = field(default_factory=dict)
    _next_id: int = 0
    _last_ts: float = 0.0
    pan_in_progress: bool = False


def _hit_centroid(hit: WorldHitDict) -> Tuple[float, float]:
    xy = hit.get("client_xy") or [0, 0]
    return float(xy[0]), float(xy[1])


def _hit_screen_xy(hit: WorldHitDict) -> Tuple[int, int]:
    xy = hit.get("screen_xy") or hit.get("client_xy") or [0, 0]
    return int(xy[0]), int(xy[1])


def _position_variance(positions: Sequence[Tuple[int, int]]) -> float:
    if len(positions) < 2:
        return float("inf")
    arr = np.array(positions, dtype=np.float64)
    return float(np.var(arr[:, 0]) + np.var(arr[:, 1]))


def _compute_velocity(
    positions: Deque[Tuple[int, int]],
    timestamps: Deque[float],
    *,
    max_samples: int,
) -> Tuple[float, float]:
    if len(positions) < 2 or len(timestamps) < 2:
        return 0.0, 0.0
    n = min(len(positions), len(timestamps), max_samples)
    if n < 2:
        return 0.0, 0.0
    pos_list = list(positions)[-n:]
    ts_list = list(timestamps)[-n:]
    dt = ts_list[-1] - ts_list[0]
    if dt <= 1e-6:
        return 0.0, 0.0
    dx = float(pos_list[-1][0] - pos_list[0][0])
    dy = float(pos_list[-1][1] - pos_list[0][1])
    return dx / dt, dy / dt


def _update_stability(track: _InternalTrack, cfg: WorldObjectTrackerConfig) -> None:
    recent = list(track.positions)[-cfg.stable_min_frames :]
    if (
        track.missed_frames == 0
        and len(recent) >= cfg.stable_min_frames
        and _position_variance(recent) <= cfg.stable_variance_threshold
    ):
        track.stable = True
    elif track.missed_frames > 0:
        track.stable = False


def _apply_hit(track: _InternalTrack, hit: WorldHitDict, ts: float, cfg: WorldObjectTrackerConfig) -> None:
    cx, cy = _hit_centroid(hit)
    track.client_xy = (int(round(cx)), int(round(cy)))
    track.screen_xy = _hit_screen_xy(hit)
    track.score = float(hit.get("score", 0.0))
    track.missed_frames = 0
    track.age_frames += 1
    track.positions.append(track.client_xy)
    track.timestamps.append(ts)
    track.velocity_xy = _compute_velocity(
        track.positions,
        track.timestamps,
        max_samples=cfg.velocity_history,
    )
    _update_stability(track, cfg)


def _extrapolate(track: _InternalTrack, dt: float) -> None:
    if dt <= 0:
        return
    vx, vy = track.velocity_xy
    if abs(vx) < 1e-6 and abs(vy) < 1e-6:
        return
    cx, cy = track.client_xy
    sx, sy = track.screen_xy
    dx = int(round(vx * dt))
    dy = int(round(vy * dt))
    track.client_xy = (cx + dx, cy + dy)
    track.screen_xy = (sx + dx, sy + dy)


def _register_track(
    state: WorldObjectTrackerState,
    hit: WorldHitDict,
    ts: float,
    cfg: WorldObjectTrackerConfig,
) -> _InternalTrack:
    oid = state._next_id
    state._next_id += 1
    client_xy = (int(round(_hit_centroid(hit)[0])), int(round(_hit_centroid(hit)[1])))
    track = _InternalTrack(
        track_id=oid,
        template=str(hit.get("template", "")),
        client_xy=client_xy,
        screen_xy=_hit_screen_xy(hit),
        score=float(hit.get("score", 0.0)),
        age_frames=1,
    )
    track.positions.append(track.client_xy)
    track.timestamps.append(ts)
    state.tracks[oid] = track
    _update_stability(track, cfg)
    return track


def _associate_template_group(
    state: WorldObjectTrackerState,
    template: str,
    hits: Sequence[WorldHitDict],
    ts: float,
    dt: float,
    cfg: WorldObjectTrackerConfig,
) -> None:
    active_ids = [
        tid
        for tid, t in state.tracks.items()
        if t.template == template and t.missed_frames <= cfg.max_missed
    ]
    if not hits and not active_ids:
        return

    if not hits:
        for tid in active_ids:
            track = state.tracks[tid]
            track.missed_frames += 1
            track.stable = False
            if cfg.extrapolate_on_miss:
                _extrapolate(track, dt)
        return

    if not active_ids:
        for hit in hits:
            _register_track(state, hit, ts, cfg)
        return

    track_ids = active_ids
    input_centroids = np.array([_hit_centroid(h) for h in hits], dtype=np.float64)
    object_centroids = np.array([state.tracks[tid].client_xy for tid in track_ids], dtype=np.float64)
    d_mat = dist.cdist(object_centroids, input_centroids)
    rows = d_mat.min(axis=1).argsort()
    cols = d_mat.argmin(axis=1)
    used_rows: set = set()
    used_cols: set = set()

    for row in rows:
        col = int(cols[row])
        if row in used_rows or col in used_cols:
            continue
        if d_mat[row, col] > cfg.max_distance:
            continue
        tid = track_ids[row]
        _apply_hit(state.tracks[tid], hits[col], ts, cfg)
        used_rows.add(row)
        used_cols.add(col)

    unused_rows = set(range(d_mat.shape[0])) - used_rows
    unused_cols = set(range(d_mat.shape[1])) - used_cols

    for row in unused_rows:
        tid = track_ids[row]
        track = state.tracks[tid]
        track.missed_frames += 1
        track.stable = False
        if cfg.extrapolate_on_miss:
            _extrapolate(track, dt)

    for col in unused_cols:
        _register_track(state, hits[col], ts, cfg)


def update_world_tracks(
    state: WorldObjectTrackerState,
    hits: Sequence[WorldHitDict],
    *,
    ts: float,
    client_w: int,
    config: Optional[WorldObjectTrackerConfig] = None,
    vision_fps: float = 10.0,
) -> List[WorldObjectTrack]:
    """
    Associate raw template hits to persistent tracks and return the active set.

    Tracks with ``missed_frames > max_missed`` are dropped. Unmatched hits spawn
    new ``track_id``s. Same-template greedy centroid matching uses
    ``scaled_max_distance(client_w)``.
    """
    cfg = config or default_world_tracker_config(client_w, vision_fps=vision_fps)
    if state.pan_in_progress:
        state.tracks.clear()
        state._last_ts = ts
        return []

    dt = ts - state._last_ts if state._last_ts > 0 else (1.0 / vision_fps if vision_fps > 0 else 0.1)
    state._last_ts = ts

    hits_by_template: Dict[str, List[WorldHitDict]] = {}
    for hit in hits:
        template = str(hit.get("template", ""))
        if not template:
            continue
        hits_by_template.setdefault(template, []).append(hit)

    templates = set(hits_by_template.keys()) | {t.template for t in state.tracks.values()}
    for template in templates:
        _associate_template_group(
            state,
            template,
            hits_by_template.get(template, []),
            ts,
            dt,
            cfg,
        )

    drop = [tid for tid, t in state.tracks.items() if t.missed_frames > cfg.max_missed]
    for tid in drop:
        state.tracks.pop(tid, None)

    return [_public_track(t) for t in state.tracks.values()]


def _public_track(track: _InternalTrack) -> WorldObjectTrack:
    return WorldObjectTrack(
        track_id=track.track_id,
        template=track.template,
        client_xy=track.client_xy,
        screen_xy=track.screen_xy,
        velocity_xy=(
            round(track.velocity_xy[0], 2),
            round(track.velocity_xy[1], 2),
        ),
        score=round(track.score, 4),
        age_frames=track.age_frames,
        missed_frames=track.missed_frames,
        stable=track.stable,
    )


def tracks_to_dict(tracks: Sequence[WorldObjectTrack]) -> List[WorldTrackDict]:
    return [
        {
            "track_id": t.track_id,
            "template": t.template,
            "client_xy": [t.client_xy[0], t.client_xy[1]],
            "screen_xy": [t.screen_xy[0], t.screen_xy[1]],
            "velocity_xy": [t.velocity_xy[0], t.velocity_xy[1]],
            "score": t.score,
            "age_frames": t.age_frames,
            "missed_frames": t.missed_frames,
            "stable": t.stable,
        }
        for t in tracks
    ]
