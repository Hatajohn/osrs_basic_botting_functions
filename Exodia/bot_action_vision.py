"""
Action-strip vision for the live perception stream (Phase 1d).

``ActionVisionProcessor`` reads capture frames + ``inventory_rect`` from
``InventoryPerceptionCache``, detects green **Fishing** / **NOT fishing** text,
and publishes debounced tri-state codes on ``/meta`` ``perception.action``.

When a synchronized ``TextPerceptionCache`` / ``ClientTextSnapshot`` is available,
``infer_action_code_from_snapshot`` (colored OCR) runs first. Idle (``1``) may be
promoted from red joined strip text, not only the NOT fishing template. Template
and green-contour detection remain the fallback when OCR is absent or returns
code ``2``.
"""
from __future__ import annotations

import math
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
from bot_client_text import ClientTextSnapshot
from bot_env import resize_image
from bot_frame_dispatch import FrameQueue
from bot_perception_worker import run_modality_loop
from bot_template_find import TemplateFinder
from bot_text_query import infer_action_code_from_snapshot
from bot_text_vision import TextPerceptionCache

Rect = List[int]

# Legacy default (top-left). Prefer left-of-inventory from stream ``inventory_rect``.
_ACTION_STRIP_RECT_CLIENT = [25, 50, 100, 30]

_ACTION_FISHING = 0
_ACTION_IDLE = 1
_ACTION_NO_UI = 2

from bot_action_templates import (
    FISHING_TEXT_TEMPLATE as _FISH_TEMPLATE,
    NOT_FISHING_TEXT_TEMPLATE as _NOT_FISH_TEMPLATE,
    action_template_paths_ok,
    load_template_gray as _load_template_gray,
    resolve_action_template_path,
)


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


def action_vision_enabled() -> bool:
    """When false, stream skips ``ActionVisionProcessor`` (``EXODIA_ACTION_VISION``)."""
    return _env_bool("EXODIA_ACTION_VISION", True)


def _template_locate_enabled() -> bool:
    """Full-frame template strip locate (expensive); default off — use ``inventory_rect``."""
    return _env_bool("EXODIA_ACTION_STRIP_TEMPLATE_LOCATE", False)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_action_vision_fps() -> float:
    raw = os.environ.get("EXODIA_ACTION_VISION_FPS", "10").strip()
    try:
        fps = float(raw)
    except ValueError:
        fps = 10.0
    return max(1.0, min(30.0, fps))


def default_action_template_threshold() -> float:
    return _env_float("EXODIA_ACTION_TEMPLATE_THRESHOLD", 0.26)


def default_action_debounce_frames() -> int:
    return max(1, _env_int("EXODIA_ACTION_DEBOUNCE_FRAMES", 3))


def _template_locate_interval_s() -> float:
    return max(5.0, _env_float("EXODIA_ACTION_STRIP_TEMPLATE_LOCATE_S", 30.0))


def _parse_rect_env(key: str) -> Optional[List[int]]:
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return None
    parts = [int(x.strip()) for x in raw.replace(" ", "").split(",")]
    if len(parts) == 4:
        return parts
    return None


def _clamp_roi(width: int, height: int, roi: Sequence[int]) -> Tuple[int, int, int, int]:
    sx, sy, sw, sh = (int(roi[i]) for i in range(4))
    sx = max(0, min(sx, width - 1))
    sy = max(0, min(sy, height - 1))
    sw = max(1, min(sw, width - sx))
    sh = max(1, min(sh, height - sy))
    return sx, sy, sw, sh


def resolve_action_strip_roi_client(
    *,
    inventory_rect: Optional[Sequence[int]] = None,
    frame_w: int = 0,
    frame_h: int = 0,
) -> List[int]:
    """Action strip ROI left of inventory (same layout as ``bot_eyes``)."""
    manual = _parse_rect_env("EXODIA_ACTION_STRIP_RECT")
    if manual:
        return manual

    if (
        _env_bool("EXODIA_ACTION_STRIP_LEFT_OF_INV", True)
        and inventory_rect is not None
        and len(inventory_rect) == 4
    ):
        ix, iy, iw, ih = (int(inventory_rect[i]) for i in range(4))
        gap = int(os.environ.get("EXODIA_ACTION_STRIP_GAP", "6"))
        tab_w = int(os.environ.get("EXODIA_ACTION_STRIP_TAB_COL_W", "34"))
        aw = int(os.environ.get("EXODIA_ACTION_STRIP_WIDTH", "100"))
        ah = int(os.environ.get("EXODIA_ACTION_STRIP_HEIGHT", "30"))
        bottom_pad = int(os.environ.get("EXODIA_ACTION_STRIP_BOTTOM_PAD", "2"))
        ax = max(0, ix - aw - gap - tab_w)
        if ax + aw >= ix:
            aw = max(80, ix - gap - tab_w - ax)
            ax = max(0, ix - aw - gap - tab_w)
        ay = max(0, iy + ih - ah - bottom_pad)
        if frame_w > 0:
            ax = min(ax, max(0, frame_w - aw))
        if frame_h > 0:
            ay = min(ay, max(0, frame_h - ah))
        return [ax, ay, aw, ah]

    return list(_ACTION_STRIP_RECT_CLIENT)


def _bottom_right_ui_search_roi(frame_w: int, frame_h: int) -> List[int]:
    raw = _parse_rect_env("EXODIA_ACTION_STRIP_SEARCH_ROI")
    if raw:
        return raw
    return [
        max(0, int(frame_w * 0.50)),
        max(0, int(frame_h * 0.52)),
        max(200, int(frame_w * 0.50)),
        max(180, int(frame_h * 0.48)),
    ]


def _match_template_peaks(
    res: np.ndarray,
    template_w: int,
    template_h: int,
    threshold: float,
    max_peaks: int = 32,
) -> List[Tuple[int, int, float]]:
    if res.size == 0:
        return []
    suppressed = res.astype(np.float64).copy()
    peaks: List[Tuple[int, int, float]] = []
    h_r, w_r = suppressed.shape[:2]
    for _ in range(max_peaks):
        _, max_val, _, max_loc = cv2.minMaxLoc(suppressed)
        if max_val < threshold or not math.isfinite(float(max_val)):
            break
        x, y = int(max_loc[0]), int(max_loc[1])
        peaks.append((x, y, float(max_val)))
        x0 = max(0, x - template_w // 2)
        y0 = max(0, y - template_h // 2)
        x1 = min(w_r, x + template_w)
        y1 = min(h_r, y + template_h)
        suppressed[y0:y1, x0:x1] = -1.0
    return peaks


def _template_path(filename: str) -> Optional[Path]:
    return resolve_action_template_path(filename)


def _action_template_scores_in_bottom_ui(client_bgr: np.ndarray) -> Tuple[float, float]:
    """Fallback scan in bottom-right UI band (``bot_eyes.get_action_text`` parity)."""
    if client_bgr is None or not getattr(client_bgr, "size", 0):
        return 0.0, 0.0
    h0, w0 = client_bgr.shape[:2]
    sx, sy, sw, sh = _clamp_roi(w0, h0, _bottom_right_ui_search_roi(w0, h0))
    patch = client_bgr[sy : sy + sh, sx : sx + sw]
    return TemplateFinder.score_action_strip_templates(patch)


def _green_status_visible(img_bgr: np.ndarray) -> bool:
    """True when green status-line contours are present (active skilling)."""
    if img_bgr is None or img_bgr.size == 0:
        return False
    img = resize_image(img_bgr, 300)
    boundaries = [([0, 250, 0], [10, 255, 10])]
    for lower, upper in boundaries:
        lower_arr = np.array(lower, dtype="uint8")
        upper_arr = np.array(upper, dtype="uint8")
        mask_g = cv2.inRange(img, lower_arr, upper_arr)
        _, thresh_g = cv2.threshold(mask_g, 40, 255, 0)
    rect_kernel_g = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    dilation_g = cv2.dilate(thresh_g, rect_kernel_g, iterations=1)
    contours_g, _ = cv2.findContours(dilation_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return len(contours_g) > 0


def _find_action_strip_rect(
    client_bgr: np.ndarray,
    *,
    threshold: float = 0.22,
) -> Optional[Rect]:
    """Locate skilling action box via fishing / NOT fishing templates."""
    h0, w0 = client_bgr.shape[:2]
    search_roi = _bottom_right_ui_search_roi(w0, h0)
    gray = cv2.cvtColor(client_bgr, cv2.COLOR_BGR2GRAY)
    sx, sy, sw, sh = _clamp_roi(w0, h0, search_roi)
    patch = gray[sy : sy + sh, sx : sx + sw]
    box_w = int(os.environ.get("EXODIA_ACTION_STRIP_WIDTH", "100"))
    box_h = int(os.environ.get("EXODIA_ACTION_STRIP_HEIGHT", "30"))
    best: Optional[Tuple[float, int, int]] = None
    for filename in (_FISH_TEMPLATE, _NOT_FISH_TEMPLATE):
        path = _template_path(filename)
        if path is None:
            continue
        template = _load_template_gray(str(path))
        if template is None:
            continue
        th, tw = template.shape[:2]
        if patch.shape[0] < th or patch.shape[1] < tw:
            continue
        res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        peaks = _match_template_peaks(res, tw, th, threshold, max_peaks=4)
        for px, py, score in peaks:
            if best is None or score > best[0]:
                cx = sx + px + tw // 2
                cy = sy + py + th // 2
                best = (score, cx, cy)
    if best is None:
        return None
    _, cx, cy = best
    ax = max(0, cx - int(box_w * 0.12))
    ay = max(0, cy - int(box_h * 0.35))
    if ax + box_w > w0:
        ax = max(0, w0 - box_w)
    if ay + box_h > h0:
        ay = max(0, h0 - box_h)
    return [ax, ay, box_w, box_h]


def _resolve_action_strip_rect(
    client_bgr: np.ndarray,
    inventory_rect: Optional[Rect],
    *,
    cached_rect: Optional[Rect] = None,
    allow_template_locate: bool = False,
) -> Rect:
    """Cheap ROI from inventory layout; optional cached / template refine."""
    if cached_rect is not None and len(cached_rect) == 4:
        return list(cached_rect)
    h0, w0 = client_bgr.shape[:2]
    if inventory_rect is not None and len(inventory_rect) == 4:
        return resolve_action_strip_roi_client(
            inventory_rect=inventory_rect,
            frame_w=w0,
            frame_h=h0,
        )
    if allow_template_locate:
        found = _find_action_strip_rect(client_bgr)
        if found is not None:
            return found
    return resolve_action_strip_roi_client(frame_w=w0, frame_h=h0)


def _crop_strip_bgr(
    client_bgr: np.ndarray,
    inventory_rect: Optional[Rect],
    *,
    cached_rect: Optional[Rect] = None,
    allow_template_locate: bool = False,
) -> Tuple[Optional[np.ndarray], Rect]:
    rect = _resolve_action_strip_rect(
        client_bgr,
        inventory_rect,
        cached_rect=cached_rect,
        allow_template_locate=allow_template_locate,
    )
    h0, w0 = client_bgr.shape[:2]
    sx, sy, sw, sh = _clamp_roi(w0, h0, rect)
    strip = client_bgr[sy : sy + sh, sx : sx + sw]
    if strip.size == 0:
        return None, rect
    return strip.copy(), rect


@dataclass(frozen=True)
class ActionDetectionResult:
    """Single-frame raw detection (before debounce)."""

    action_code: int
    fishing_visible: bool
    not_fishing_visible: bool
    strip_visible: bool
    fish_template_score: float
    not_fish_template_score: float
    action_strip_rect: Optional[Rect]
    action_line_text: Optional[str] = None
    action_line_color: Optional[str] = None
    detection_source: str = "none"


def _text_snapshot_matches_frame(
    text_snapshot: Optional[ClientTextSnapshot],
    *,
    frame_seq: Optional[int] = None,
    capture_seq: Optional[int] = None,
) -> bool:
    if text_snapshot is None:
        return False
    if frame_seq is not None and text_snapshot.processed_seq == int(frame_seq):
        return True
    if capture_seq is not None and (
        text_snapshot.capture_seq == int(capture_seq)
        or text_snapshot.processed_seq == int(capture_seq)
    ):
        return True
    return False


def _try_ocr_action_detection(
    text_snapshot: Optional[ClientTextSnapshot],
    strip_rect: Optional[Rect],
    *,
    frame_seq: Optional[int] = None,
    capture_seq: Optional[int] = None,
    template_threshold: float,
    fish_s: float,
    idle_s: float,
) -> Optional[ActionDetectionResult]:
    """Colored OCR first when text snapshot is synchronized with the vision frame."""
    if strip_rect is None:
        return None
    if not _text_snapshot_matches_frame(
        text_snapshot, frame_seq=frame_seq, capture_seq=capture_seq
    ):
        # Allow slightly stale text (text worker often runs below action FPS).
        if text_snapshot is None or frame_seq is None:
            return None
        try:
            lag = abs(int(text_snapshot.processed_seq) - int(frame_seq))
        except (TypeError, ValueError):
            return None
        if lag > 3:
            return None
    inference = infer_action_code_from_snapshot(
        text_snapshot,
        strip_rect=strip_rect,
        template_threshold=template_threshold,
    )
    if inference.action_code == _ACTION_NO_UI:
        return None
    if inference.action_code == _ACTION_IDLE:
        return ActionDetectionResult(
            action_code=_ACTION_IDLE,
            fishing_visible=False,
            not_fishing_visible=True,
            strip_visible=True,
            fish_template_score=fish_s,
            not_fish_template_score=idle_s,
            action_strip_rect=strip_rect,
            action_line_text=inference.action_line_text,
            action_line_color=inference.action_line_color,
            detection_source=inference.detection_source,
        )
    if inference.action_code == _ACTION_FISHING:
        return ActionDetectionResult(
            action_code=_ACTION_FISHING,
            fishing_visible=True,
            not_fishing_visible=False,
            strip_visible=True,
            fish_template_score=fish_s,
            not_fish_template_score=idle_s,
            action_strip_rect=strip_rect,
            action_line_text=inference.action_line_text,
            action_line_color=inference.action_line_color,
            detection_source=inference.detection_source,
        )
    return None


def detect_action_strip(
    client_bgr: np.ndarray,
    inventory_rect: Optional[Rect],
    *,
    template_threshold: Optional[float] = None,
    cached_strip_rect: Optional[Rect] = None,
    allow_template_locate: bool = False,
    text_snapshot: Optional[ClientTextSnapshot] = None,
    frame_seq: Optional[int] = None,
    capture_seq: Optional[int] = None,
) -> ActionDetectionResult:
    """
    Asymmetric tri-state detection for stream FSM gating.

    When ``text_snapshot`` is synchronized with the frame, colored OCR runs first
    (red joined strip text may promote idle ``1``). Template / contour fallback
    applies when OCR is unavailable or returns code ``2``.

    - ``1`` when NOT fishing OCR or template is confident.
    - ``0`` when green status line, fishing OCR, or fishing template dominates.
    - ``2`` otherwise (hidden strip, pre-first-cast, ambiguous).
    """
    thr = template_threshold if template_threshold is not None else default_action_template_threshold()
    if client_bgr is None or not getattr(client_bgr, "size", 0):
        return ActionDetectionResult(
            action_code=_ACTION_NO_UI,
            fishing_visible=False,
            not_fishing_visible=False,
            strip_visible=False,
            fish_template_score=0.0,
            not_fish_template_score=0.0,
            action_strip_rect=None,
        )

    strip, strip_rect = _crop_strip_bgr(
        client_bgr,
        inventory_rect,
        cached_rect=cached_strip_rect,
        allow_template_locate=allow_template_locate,
    )
    fish_s = 0.0
    idle_s = 0.0
    green_visible = False
    if strip is not None and strip.size > 0:
        fish_s, idle_s = TemplateFinder.score_action_strip_templates(strip)
        green_visible = _green_status_visible(strip)

    # Weak strip ROI — search bottom-right UI and refine rect via template peaks.
    weak = max(fish_s, idle_s) < thr * 0.45 and not green_visible
    if weak:
        fish_ui, idle_ui = _action_template_scores_in_bottom_ui(client_bgr)
        if max(fish_ui, idle_ui) > max(fish_s, idle_s):
            fish_s, idle_s = fish_ui, idle_ui
        found = _find_action_strip_rect(client_bgr, threshold=thr * 0.85)
        if found is not None:
            h0, w0 = client_bgr.shape[:2]
            sx, sy, sw, sh = _clamp_roi(w0, h0, found)
            refined = client_bgr[sy : sy + sh, sx : sx + sw]
            if refined.size > 0:
                strip_rect = found
                strip = refined.copy()
                fish_s, idle_s = TemplateFinder.score_action_strip_templates(strip)
                green_visible = _green_status_visible(strip)

    ocr_hit = _try_ocr_action_detection(
        text_snapshot,
        strip_rect,
        frame_seq=frame_seq,
        capture_seq=capture_seq,
        template_threshold=thr,
        fish_s=fish_s,
        idle_s=idle_s,
    )
    if ocr_hit is not None:
        return ocr_hit

    not_fishing_confident = idle_s >= thr and idle_s >= fish_s
    fishing_template_confident = fish_s >= thr and fish_s >= idle_s

    if not_fishing_confident:
        return ActionDetectionResult(
            action_code=_ACTION_IDLE,
            fishing_visible=False,
            not_fishing_visible=True,
            strip_visible=True,
            fish_template_score=fish_s,
            not_fish_template_score=idle_s,
            action_strip_rect=strip_rect,
            detection_source="template",
        )

    if green_visible or fishing_template_confident:
        return ActionDetectionResult(
            action_code=_ACTION_FISHING,
            fishing_visible=True,
            not_fishing_visible=False,
            strip_visible=green_visible or fishing_template_confident,
            fish_template_score=fish_s,
            not_fish_template_score=idle_s,
            action_strip_rect=strip_rect,
            detection_source="contour" if green_visible and not fishing_template_confident else "template",
        )

    return ActionDetectionResult(
        action_code=_ACTION_NO_UI,
        fishing_visible=False,
        not_fishing_visible=False,
        strip_visible=strip is not None and strip.size > 0 and max(fish_s, idle_s) > 0.12,
        fish_template_score=fish_s,
        not_fish_template_score=idle_s,
        action_strip_rect=strip_rect,
        detection_source="none",
    )


@dataclass(frozen=True)
class ActionPerceptionSnapshot:
    action_code: int
    fishing_visible: bool
    not_fishing_visible: bool
    strip_visible: bool
    action_strip_rect: Optional[Rect]
    fish_template_score: float
    not_fish_template_score: float
    action_line_text: Optional[str]
    action_line_color: Optional[str]
    detection_source: str
    processed_seq: int
    capture_seq: int
    ts: float
    vision_fps: float


@dataclass
class ActionPerceptionCache:
    """Thread-safe debounced action-strip state for ``/meta``."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _action_code: int = _ACTION_NO_UI
    _fishing_visible: bool = False
    _not_fishing_visible: bool = False
    _strip_visible: bool = False
    _action_strip_rect: Optional[Rect] = None
    _fish_template_score: float = 0.0
    _not_fish_template_score: float = 0.0
    _action_line_text: Optional[str] = None
    _action_line_color: Optional[str] = None
    _detection_source: str = "none"
    _processed_seq: int = 0
    _capture_seq: int = 0
    _ts: float = 0.0
    _vision_fps: float = 0.0
    _debounce_buffer: Deque[int] = field(default_factory=lambda: deque(maxlen=8))

    def update_from_detection(
        self,
        raw: ActionDetectionResult,
        *,
        processed_seq: int,
        capture_seq: int,
        vision_fps: float,
        debounce_frames: int,
    ) -> Optional[int]:
        """
        Push raw code into debounce buffer; update published state when stable.

        Returns previous ``action_code`` when a debounced transition occurred, else ``None``.
        """
        n = max(1, debounce_frames)
        with self._lock:
            self._debounce_buffer.append(int(raw.action_code))
            buf = list(self._debounce_buffer)
            if len(buf) < n:
                return None
            window = buf[-n:]
            if len(set(window)) != 1:
                return None
            stable_code = window[-1]
            prev_code = self._action_code
            self._fishing_visible = bool(raw.fishing_visible)
            self._not_fishing_visible = bool(raw.not_fishing_visible)
            self._strip_visible = bool(raw.strip_visible)
            self._action_strip_rect = (
                list(raw.action_strip_rect) if raw.action_strip_rect is not None else None
            )
            self._fish_template_score = float(raw.fish_template_score)
            self._not_fish_template_score = float(raw.not_fish_template_score)
            self._action_line_text = raw.action_line_text
            self._action_line_color = raw.action_line_color
            self._detection_source = str(raw.detection_source)
            self._processed_seq = int(processed_seq)
            self._capture_seq = int(capture_seq)
            self._ts = time.monotonic()
            self._vision_fps = float(vision_fps)
            if stable_code == self._action_code:
                return None
            self._action_code = stable_code
            return prev_code

    def snapshot(self) -> ActionPerceptionSnapshot:
        with self._lock:
            return ActionPerceptionSnapshot(
                action_code=self._action_code,
                fishing_visible=self._fishing_visible,
                not_fishing_visible=self._not_fishing_visible,
                strip_visible=self._strip_visible,
                action_strip_rect=(
                    list(self._action_strip_rect) if self._action_strip_rect is not None else None
                ),
                fish_template_score=self._fish_template_score,
                not_fish_template_score=self._not_fish_template_score,
                action_line_text=self._action_line_text,
                action_line_color=self._action_line_color,
                detection_source=self._detection_source,
                processed_seq=self._processed_seq,
                capture_seq=self._capture_seq,
                ts=self._ts,
                vision_fps=self._vision_fps,
            )

    def action_meta(self) -> Dict[str, Any]:
        snap = self.snapshot()
        return {
            "action_code": snap.action_code,
            "fishing_visible": snap.fishing_visible,
            "not_fishing_visible": snap.not_fishing_visible,
            "strip_visible": snap.strip_visible,
            "action_strip_rect": (
                list(snap.action_strip_rect) if snap.action_strip_rect is not None else None
            ),
            "fish_template_score": round(snap.fish_template_score, 4),
            "not_fish_template_score": round(snap.not_fish_template_score, 4),
            "action_line_text": snap.action_line_text,
            "action_line_color": snap.action_line_color,
            "detection_source": snap.detection_source,
            "processed_seq": snap.processed_seq,
            "capture_seq": snap.capture_seq,
            "vision_fps": round(snap.vision_fps, 2),
        }


class ActionVisionProcessor:
    """Daemon thread: action-strip detect at ``EXODIA_ACTION_VISION_FPS``."""

    def __init__(
        self,
        buffer: FrameBuffer,
        inv_cache: Any,
        action_cache: ActionPerceptionCache,
        *,
        frame_queue: Optional[FrameQueue] = None,
        fps: Optional[float] = None,
        template_threshold: Optional[float] = None,
        debounce_frames: Optional[int] = None,
        text_cache: Optional[TextPerceptionCache] = None,
    ) -> None:
        self._buffer = buffer
        self._frame_queue = frame_queue
        self._inv_cache = inv_cache
        self._cache = action_cache
        self._text_cache = text_cache
        self._fps = fps if fps is not None else default_action_vision_fps()
        self._template_threshold = (
            template_threshold
            if template_threshold is not None
            else default_action_template_threshold()
        )
        self._debounce_frames = (
            debounce_frames
            if debounce_frames is not None
            else default_action_debounce_frames()
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_processed_seq = 0
        self._actual_fps = 0.0
        self._cached_strip_rect: Optional[Rect] = None
        self._last_template_locate_mono = 0.0
        self._last_error_log_mono = 0.0

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
            target=self._run_vision, name="ActionVisionProcessor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _maybe_refresh_template_strip_rect(
        self,
        client_bgr: np.ndarray,
        inventory_rect: Optional[Rect],
        *,
        force: bool = False,
    ) -> None:
        if not force and inventory_rect is not None and len(inventory_rect) == 4:
            if not _template_locate_enabled():
                return
        if not force and not _template_locate_enabled():
            return
        now = time.monotonic()
        if not force and now - self._last_template_locate_mono < _template_locate_interval_s():
            return
        self._last_template_locate_mono = now
        found = _find_action_strip_rect(client_bgr)
        if found is not None:
            self._cached_strip_rect = found

    def _text_snapshot_for_frame(self, snap: FrameSnapshot) -> Optional[ClientTextSnapshot]:
        if self._text_cache is None:
            return None
        ts = self._text_cache.snapshot()
        text_snap = ClientTextSnapshot(
            spans=ts.spans,
            processed_seq=ts.processed_seq,
            capture_seq=ts.capture_seq,
            client_size=ts.client_size,
            elapsed_ms=ts.elapsed_ms,
        )
        if not _text_snapshot_matches_frame(
            text_snap,
            frame_seq=snap.seq,
            capture_seq=self._capture_seq(snap),
        ):
            return None
        return text_snap

    def _process_frame(self, snap: FrameSnapshot) -> None:
        inv_snap = self._inv_cache.snapshot()
        inventory_rect = inv_snap.inventory_rect
        client_bgr = snap.bgr
        if client_bgr is None or not getattr(client_bgr, "size", 0):
            return
        self._maybe_refresh_template_strip_rect(client_bgr, inventory_rect)
        if inventory_rect is not None and len(inventory_rect) == 4:
            h0, w0 = client_bgr.shape[:2]
            if self._cached_strip_rect is None:
                self._cached_strip_rect = resolve_action_strip_roi_client(
                    inventory_rect=inventory_rect,
                    frame_w=w0,
                    frame_h=h0,
                )
        text_snapshot = self._text_snapshot_for_frame(snap)
        capture_seq = self._capture_seq(snap)
        raw = detect_action_strip(
            client_bgr,
            inventory_rect,
            template_threshold=self._template_threshold,
            cached_strip_rect=self._cached_strip_rect,
            allow_template_locate=False,
            text_snapshot=text_snapshot,
            frame_seq=snap.seq,
            capture_seq=capture_seq,
        )
        if (
            max(raw.fish_template_score, raw.not_fish_template_score) < self._template_threshold * 0.45
            and not raw.fishing_visible
        ):
            self._maybe_refresh_template_strip_rect(
                client_bgr, inventory_rect, force=True
            )
            raw = detect_action_strip(
                client_bgr,
                inventory_rect,
                template_threshold=self._template_threshold,
                cached_strip_rect=self._cached_strip_rect,
                allow_template_locate=False,
                text_snapshot=text_snapshot,
                frame_seq=snap.seq,
                capture_seq=capture_seq,
            )
        if raw.action_strip_rect is not None:
            self._cached_strip_rect = list(raw.action_strip_rect)
        self._cache.update_from_detection(
            raw,
            processed_seq=snap.seq,
            capture_seq=self._capture_seq(snap),
            vision_fps=self._actual_fps if self._actual_fps > 0 else self._fps,
            debounce_frames=self._debounce_frames,
        )

    def _run_vision(self) -> None:
        def _process(snap: FrameSnapshot) -> None:
            try:
                self._process_frame(snap)
            except Exception as exc:
                now = time.monotonic()
                if now - self._last_error_log_mono >= 10.0:
                    self._last_error_log_mono = now
                    print("ActionVisionProcessor error: %s" % exc)

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
    "ActionDetectionResult",
    "ActionPerceptionCache",
    "ActionPerceptionSnapshot",
    "ActionVisionProcessor",
    "action_template_paths_ok",
    "action_vision_enabled",
    "default_action_debounce_frames",
    "default_action_template_threshold",
    "default_action_vision_fps",
    "detect_action_strip",
    "resolve_action_strip_roi_client",
    "resolve_action_template_path",
]
