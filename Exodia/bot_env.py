from __future__ import annotations

import os
import cv2
import time
import math
import random
import numpy as np
from typing import Dict, Iterable, Optional, Tuple, Union

from PIL import ImageGrab

# OSRS server/client tick ~0.6s; align sense/act loops when simulating tick fidelity.
PERF_TICK_S = 0.6

Rect = Union[List[int], Tuple[int, int, int, int]]


def _capture_backend() -> str:
    return (os.environ.get("EXODIA_CAPTURE_BACKEND") or "pil").strip().lower()


def _grab_bgr_pil(left: int, top: int, w: int, h: int) -> np.ndarray:
    bbox = (left, top, left + w, top + h)
    shot = ImageGrab.grab(bbox=bbox)
    return cv2.cvtColor(np.asarray(shot), cv2.COLOR_RGB2BGR)


def _grab_bgr_mss(left: int, top: int, w: int, h: int) -> np.ndarray:
    import mss

    with mss.mss() as sct:
        region = {"left": left, "top": top, "width": w, "height": h}
        raw = sct.grab(region)
        frame = np.asarray(raw)  # BGRA
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def _grab_bgr(left: int, top: int, w: int, h: int) -> np.ndarray:
    if _capture_backend() == "mss":
        return _grab_bgr_mss(left, top, w, h)
    return _grab_bgr_pil(left, top, w, h)


def human_pause(base_seconds, jitter_ratio=0.35):
    """Sleep base_seconds +/- random jitter (0 .. jitter_ratio*base). Keeps pacing less uniform."""
    if base_seconds <= 0:
        return
    span = base_seconds * jitter_ratio
    low = max(0.0, base_seconds - span)
    high = base_seconds + span
    time.sleep(random.uniform(low, high))


def screen_image(
    rect: Optional[Rect] = None, name: str = "BotEnv_Screenshot", DEBUG: bool = False
):
    """
    Capture BGR image. ``rect`` is [left, top, width, height] in screen coordinates.
    Set ``EXODIA_CAPTURE_BACKEND=mss`` for mss (often faster on Linux); default ``pil``.
    """
    if rect is None:
        left, top, w, h = 0, 0, 1920, 1080
    else:
        left, top, w, h = rect[0], rect[1], rect[2], rect[3]

    image = _grab_bgr(int(left), int(top), int(w), int(h))

    if DEBUG:
        debug_view(image, title=name)

    return image


def screen_image_fast(
    rect: Rect, name: str = "BotEnv_Fast", DEBUG: bool = False
):
    """Alias for :func:`screen_image` (same backend switch); use for clarity at call sites."""
    return screen_image(rect=rect, name=name, DEBUG=DEBUG)


def screen_regions(
    regions: Iterable[Tuple[str, Rect]],
    debug: bool = False,
) -> Dict[str, np.ndarray]:
    """
    Capture multiple ROIs in one tick without duplicating full-client logic.
    ``regions`` is (label, [left, top, w, h]) screen-coordinate rectangles.
    """
    out: Dict[str, np.ndarray] = {}
    for label, rect in regions:
        r = [rect[0], rect[1], rect[2], rect[3]]
        out[label] = screen_image(rect=r, name=label if debug else "BotEnv_roi", DEBUG=debug)
    return out


def resize_image(image, scale_percent):
    width = int(image.shape[1] * scale_percent / 100)
    height = int(image.shape[0] * scale_percent / 100)
    dim = (width, height)
    return cv2.resize(image, dim, interpolation=cv2.INTER_AREA)


def block_name(image, corner=None):
    if corner is not None:
        return cv2.rectangle(image, [corner[0], corner[1], 500, 20], color=(0, 0, 0), thickness=-1)
    return cv2.rectangle(image, [0, 0, 500, 25], color=(0, 0, 0), thickness=-1)


def debug_view(img, title="Debug Screenshot", scale=60):
    arr = np.asarray(img, dtype=np.uint8)
    image = arr.copy()
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)
    time.sleep(0.5)


def pick_point_in_circle(point, rad=15):
    alpha = 2 * math.pi * random.random()

    u = random.random()
    v = random.random()
    r = min(rad, abs(rad * (1 - u if u > 0.6 else 1 - v)))

    x = int(r * math.cos(alpha) + point[0])
    y = int(r * math.sin(alpha) + point[1])

    return (x, y)
