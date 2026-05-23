"""
Blob motion tracking on the OSRS playspace (v1).

Frame-diff + contour blobs + greedy centroid IDs (CentroidTracker pattern).
Not for NPC identity, stationary targets, or click-accurate feet — see module
limitations in ``TrackState`` docstring.

Called from ``bot_capture.VisionProcessor`` only when the capture pipeline is active.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

import cv2
import numpy as np
from scipy.spatial import distance as dist

from bot_search import playspace_search_roi

if TYPE_CHECKING:
    import bot_eyes as Eyes

Rect = List[int]

# pageauc defaults @ 320×240; scale min_area to playspace size at runtime.
_REF_AREA = 320 * 240
_REF_MIN_AREA = 200
_DIFF_THRESHOLD = 20
_BLUR_SIZE = 10
_REF_MAX_DISTANCE = 50
_REF_PLAYSPACE_W = 500

__all__ = [
    "Track",
    "TrackState",
    "TrackConfig",
    "playspace_bgr",
    "playspace_bgr_from_frame",
    "motion_mask",
    "detect_blobs",
    "update_tracks",
    "track_blobs",
    "track_blobs_from_frame",
    "overlay_tracks",
    "tracks_to_dict",
    "scaled_min_area",
    "scaled_max_distance",
]


@dataclass
class Track:
    track_id: int
    centroid: Tuple[int, int]
    bbox: Rect  # [x, y, w, h] client-local
    area: float
    missed: int = 0


@dataclass
class TrackState:
    """
    Mutable blob tracker state.

    v1 limitations: no NPC identity; stationary objects invisible; centroid ≠ tile;
    IDs break during camera pan — set ``pan_in_progress`` to skip updates.
    """

    prev_playspace: Optional[np.ndarray] = None
    tracks: List[Track] = field(default_factory=list)
    frame_seq: int = 0
    pan_in_progress: bool = False
    _next_id: int = 0
    _objects: OrderedDict = field(default_factory=OrderedDict)
    _disappeared: OrderedDict = field(default_factory=OrderedDict)


@dataclass(frozen=True)
class TrackConfig:
    diff_threshold: int = _DIFF_THRESHOLD
    blur_size: int = _BLUR_SIZE
    min_area: int = _REF_MIN_AREA
    max_distance: float = _REF_MAX_DISTANCE
    max_disappeared: int = 4
    dilate_iterations: int = 2


def scaled_min_area(playspace_w: int, playspace_h: int) -> int:
    area = max(1, int(playspace_w) * int(playspace_h))
    return max(50, int(_REF_MIN_AREA * area / _REF_AREA))


def scaled_max_distance(playspace_w: int) -> float:
    return max(20.0, _REF_MAX_DISTANCE * float(playspace_w) / _REF_PLAYSPACE_W)


def default_track_config(playspace_w: int, playspace_h: int, capture_fps: float = 4.0) -> TrackConfig:
    return TrackConfig(
        min_area=scaled_min_area(playspace_w, playspace_h),
        max_distance=scaled_max_distance(playspace_w),
        max_disappeared=max(2, int(round(capture_fps))),
    )


def playspace_bgr_from_frame(frame_bgr: np.ndarray) -> Optional[np.ndarray]:
    """Crop main playspace from a full client BGR frame."""
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    h0, w0 = frame_bgr.shape[:2]
    roi = playspace_search_roi(w0, h0)
    if roi is None:
        return None
    x, y, w, h = [int(v) for v in roi]
    return np.asarray(frame_bgr[y : y + h, x : x + w], dtype=np.uint8).copy()


def playspace_bgr(eyes: "Eyes.BotEyes") -> Optional[np.ndarray]:
    """Crop playspace from ``BotEyes`` unmasked client frame."""
    base = eyes.curr_client_unmasked if eyes.curr_client_unmasked is not None else eyes.curr_client
    return playspace_bgr_from_frame(base)


def _zero_rects_on_gray(gray: np.ndarray, rects: Sequence[Rect]) -> None:
    for rect in rects:
        if rect is None or len(rect) != 4:
            continue
        x, y, w, h = [int(v) for v in rect]
        if w <= 0 or h <= 0:
            continue
        x2, y2 = min(gray.shape[1], x + w), min(gray.shape[0], y + h)
        x, y = max(0, x), max(0, y)
        if x2 > x and y2 > y:
            gray[y:y2, x:x2] = 0


def motion_mask(
    prev: np.ndarray,
    curr: np.ndarray,
    static_exclude: Optional[Sequence[Rect]] = None,
    *,
    config: Optional[TrackConfig] = None,
) -> np.ndarray:
    """
    Absolute diff motion mask on grayscale playspace crops.

    ``static_exclude`` rects are client-local regions zeroed before diff (inventory/chat).
    """
    cfg = config or TrackConfig()
    if prev is None or curr is None or prev.size == 0 or curr.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    if prev.shape != curr.shape:
        return np.zeros(curr.shape[:2], dtype=np.uint8)

    g0 = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY) if prev.ndim == 3 else prev.copy()
    g1 = cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY) if curr.ndim == 3 else curr.copy()
    if static_exclude:
        _zero_rects_on_gray(g0, static_exclude)
        _zero_rects_on_gray(g1, static_exclude)

    delta = cv2.absdiff(g0, g1)
    k = max(3, cfg.blur_size | 1)
    blurred = cv2.blur(delta, (k, k))
    _, thresh = cv2.threshold(blurred, cfg.diff_threshold, 255, cv2.THRESH_BINARY)
    if cfg.dilate_iterations > 0:
        thresh = cv2.dilate(thresh, None, iterations=cfg.dilate_iterations)
    return thresh


def detect_blobs(
    mask: np.ndarray,
    *,
    min_area: Optional[int] = None,
    offset_xy: Tuple[int, int] = (0, 0),
) -> List[Dict[str, Any]]:
    """Contours on ``mask`` → blob dicts with bbox/centroid in client-local coords."""
    if mask is None or mask.size == 0:
        return []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ox, oy = offset_xy
    min_a = int(min_area if min_area is not None else _REF_MIN_AREA)
    blobs: List[Dict[str, Any]] = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < min_a:
            continue
        x, y, w, h = cv2.boundingRect(c)
        cx, cy = int(x + w / 2) + ox, int(y + h / 2) + oy
        blobs.append(
            {
                "bbox": [x + ox, y + oy, w, h],
                "centroid": (cx, cy),
                "area": area,
            }
        )
    return blobs


def update_tracks(
    state: TrackState,
    detections: Sequence[Dict[str, Any]],
    *,
    config: Optional[TrackConfig] = None,
) -> List[Track]:
    """
    Greedy nearest-centroid ID assignment with ``max_distance`` gate (people-counter fork).
    """
    cfg = config or TrackConfig()
    if state.pan_in_progress:
        state.tracks = []
        state._objects.clear()
        state._disappeared.clear()
        return []

    rects = [tuple(d["bbox"]) for d in detections]
    if len(rects) == 0:
        for oid in list(state._disappeared.keys()):
            state._disappeared[oid] += 1
            if state._disappeared[oid] > cfg.max_disappeared:
                state._objects.pop(oid, None)
                state._disappeared.pop(oid, None)
        state.tracks = _tracks_from_objects(state)
        return state.tracks

    input_centroids = np.array(
        [[(r[0] + r[2] / 2.0), (r[1] + r[3] / 2.0)] for r in rects],
        dtype=np.float64,
    )

    if len(state._objects) == 0:
        for i in range(len(input_centroids)):
            _register(state, input_centroids[i], detections[i])
    else:
        object_ids = list(state._objects.keys())
        object_centroids = np.array(list(state._objects.values()), dtype=np.float64)
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
            oid = object_ids[row]
            state._objects[oid] = input_centroids[col]
            state._disappeared[oid] = 0
            used_rows.add(row)
            used_cols.add(col)

        unused_rows = set(range(d_mat.shape[0])) - used_rows
        unused_cols = set(range(d_mat.shape[1])) - used_cols

        if d_mat.shape[0] >= d_mat.shape[1]:
            for row in unused_rows:
                oid = object_ids[row]
                state._disappeared[oid] += 1
                if state._disappeared[oid] > cfg.max_disappeared:
                    state._objects.pop(oid, None)
                    state._disappeared.pop(oid, None)
        else:
            for col in unused_cols:
                _register(state, input_centroids[col], detections[col])

    state.tracks = _tracks_from_objects(state, detections)
    return state.tracks


def _register(state: TrackState, centroid: np.ndarray, det: Dict[str, Any]) -> None:
    oid = state._next_id
    state._next_id += 1
    state._objects[oid] = centroid
    state._disappeared[oid] = 0


def _tracks_from_objects(
    state: TrackState,
    detections: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Track]:
    det_by_centroid: Dict[Tuple[int, int], Dict[str, Any]] = {}
    if detections:
        for d in detections:
            c = d["centroid"]
            det_by_centroid[(int(c[0]), int(c[1]))] = d

    out: List[Track] = []
    for oid, cent in state._objects.items():
        cx, cy = int(cent[0]), int(cent[1])
        det = det_by_centroid.get((cx, cy))
        bbox = det["bbox"] if det else [cx - 5, cy - 5, 10, 10]
        area = det["area"] if det else 0.0
        out.append(
            Track(
                track_id=oid,
                centroid=(cx, cy),
                bbox=list(bbox),
                area=float(area),
                missed=int(state._disappeared.get(oid, 0)),
            )
        )
    return out


def track_blobs_from_frame(
    frame_bgr: np.ndarray,
    state: TrackState,
    *,
    static_exclude: Optional[Sequence[Rect]] = None,
    config: Optional[TrackConfig] = None,
    playspace_offset: Optional[Tuple[int, int]] = None,
) -> Tuple[List[Track], float]:
    """
    Run one blob tracking step on a raw client BGR frame.

    Returns ``(tracks, motion_magnitude)`` where motion_magnitude is mean diff in playspace.
    """
    play = playspace_bgr_from_frame(frame_bgr)
    if play is None:
        return [], 0.0

    h0, w0 = frame_bgr.shape[:2]
    roi = playspace_search_roi(w0, h0)
    offset = (int(roi[0]), int(roi[1])) if roi else (0, 0)
    if playspace_offset is not None:
        offset = playspace_offset

    exclude_in_play: List[Rect] = []
    if static_exclude:
        ox, oy = offset
        for rect in static_exclude:
            if rect is None or len(rect) != 4:
                continue
            exclude_in_play.append(
                [rect[0] - ox, rect[1] - oy, rect[2], rect[3]]
            )

    cfg = config or default_track_config(play.shape[1], play.shape[0])
    prev = state.prev_playspace
    mask = motion_mask(prev, play, exclude_in_play, config=cfg)
    motion_mag = float(mask.mean()) if mask.size else 0.0

    blobs = detect_blobs(mask, min_area=cfg.min_area, offset_xy=offset)
    state.frame_seq += 1
    state.prev_playspace = play.copy()
    tracks = update_tracks(state, blobs, config=cfg)
    return tracks, motion_mag


def track_blobs(
    eyes: "Eyes.BotEyes",
    state: TrackState,
    *,
    config: Optional[TrackConfig] = None,
) -> List[Track]:
    """Sync-path wrapper using ``BotEyes`` frames (tests / no pipeline)."""
    base = eyes.curr_client_unmasked if eyes.curr_client_unmasked is not None else eyes.curr_client
    if base is None:
        return []
    exclude: List[Rect] = []
    if eyes.inventory_rect and len(eyes.inventory_rect) == 4:
        exclude.append(list(eyes.inventory_rect))
    if eyes.chat_rect and len(eyes.chat_rect) == 4:
        exclude.append(list(eyes.chat_rect))
    tracks, _ = track_blobs_from_frame(base, state, static_exclude=exclude, config=config)
    return tracks


def overlay_tracks(bgr: np.ndarray, tracks: Sequence[Track]) -> np.ndarray:
    """Draw bboxes + IDs on a BGR copy."""
    out = np.asarray(bgr, dtype=np.uint8).copy()
    for t in tracks:
        x, y, w, h = [int(v) for v in t.bbox]
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(
            out,
            str(t.track_id),
            (x, max(0, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return out


def tracks_to_dict(tracks: Sequence[Track]) -> List[Dict[str, Any]]:
    return [
        {
            "id": t.track_id,
            "centroid": list(t.centroid),
            "bbox": list(t.bbox),
            "area": t.area,
            "missed": t.missed,
        }
        for t in tracks
    ]
