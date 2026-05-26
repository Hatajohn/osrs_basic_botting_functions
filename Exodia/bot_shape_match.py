"""
Shape-focused template matching for world objects and inventory icons.

Matches the **main item silhouette** (template alpha or derived body mask), not
RuneLite cyan tile markers. Optional scene prep neutralizes fishing ripples and
UI highlight colors before ``matchTemplate``.
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_env import env_float_any, env_is_set, inventory_identify_threshold

Peak = Tuple[int, int, float]


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def shape_match_enabled() -> bool:
    """Default on — use ``EXODIA_SHAPE_MATCH=0`` to disable scene/template shape prep."""
    return _env_bool("EXODIA_SHAPE_MATCH", True)


def shape_match_threshold(explicit: Optional[float] = None) -> float:
    """Threshold for playspace shape ``matchTemplate``. Short: ``EXO_SHAPE_THR``, ``EXO_SPOT_THR``."""
    if explicit is not None:
        return float(explicit)
    if env_is_set("EXO_SHAPE_THR", "EXODIA_SHAPE_MATCH_THRESHOLD"):
        return env_float_any(0.58, "EXO_SHAPE_THR", "EXODIA_SHAPE_MATCH_THRESHOLD")
    if env_is_set("EXO_SPOT_THR", "EXODIA_SPOT_THRESHOLD"):
        return env_float_any(0.45, "EXO_SPOT_THR", "EXODIA_SPOT_THRESHOLD")
    return 0.58


def inventory_template_threshold(explicit: Optional[float] = None) -> float:
    """
    Threshold for inventory template click / Find (default 0.35).

    Short env: ``EXO_INV_THR``. Legacy: ``EXODIA_INV_TEMPLATE_THRESHOLD``.
    If neither is set, falls back to identify threshold (``EXO_INV_ID_THR``, default 0.40).
    """
    if explicit is not None:
        return float(explicit)
    if env_is_set("EXO_INV_THR", "EXODIA_INV_TEMPLATE_THRESHOLD"):
        return env_float_any(0.35, "EXO_INV_THR", "EXODIA_INV_TEMPLATE_THRESHOLD")
    if env_is_set("EXO_INV_ID_THR", "EXODIA_INV_ITEM_MATCH_THRESHOLD"):
        return inventory_identify_threshold()
    return 0.35


def shape_preprocess_playspace() -> bool:
    """Scene + template prep for world / fishing spots."""
    return shape_match_enabled()


def shape_preprocess_inventory() -> bool:
    """Inventory uses template mask only (no ripple/tag scene prep by default)."""
    if not shape_match_enabled():
        return False
    return _env_bool("EXODIA_SHAPE_MATCH_INV_SCENE", False)


def _fishing_ripple_mask(hsv: np.ndarray) -> np.ndarray:
    """Bright green fishing-spot ripple animation (infernal / sacred spots)."""
    return cv2.inRange(hsv, (35, 90, 90), (88, 255, 255))


def prepare_gray_for_shape_match(
    bgr: np.ndarray,
    gray: np.ndarray,
    *,
    playspace: bool = True,
) -> np.ndarray:
    """
    Neutralize unstable pixels before matching.

    Playspace: RuneLite ground tags + optional fishing ripples.
    Inventory: unchanged (slot icons are small; scene prep often removes item pixels).
    """
    if not playspace or bgr is None or bgr.size == 0 or gray is None or gray.size == 0:
        return gray
    from bot_inventory_count import _mask_runelite_tags_in_gray

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    out = _mask_runelite_tags_in_gray(gray, hsv)
    if _env_bool("EXODIA_SHAPE_MASK_FISHING_GREEN", True):
        ripple = _fishing_ripple_mask(hsv)
        if cv2.countNonZero(ripple) > 0 and np.any(ripple == 0):
            fill = int(np.median(out[ripple == 0]))
            out = out.copy()
            out[ripple > 0] = fill
    return out


def body_mask_from_template_gray(gray_tpl: np.ndarray) -> Optional[np.ndarray]:
    """
    Derive a match mask from the template when PNG has no alpha: keep pixels that
    differ from the corner/edge background (the item body vs lava plate).
    """
    if gray_tpl is None or gray_tpl.size == 0:
        return None
    h, w = gray_tpl.shape[:2]
    corners = [
        gray_tpl[0, 0],
        gray_tpl[0, w - 1],
        gray_tpl[h - 1, 0],
        gray_tpl[h - 1, w - 1],
    ]
    bg = int(np.median(corners))
    delta = int(os.environ.get("EXODIA_SHAPE_BODY_DELTA", "14") or "14")
    body = (np.abs(gray_tpl.astype(np.int16) - bg) > delta).astype(np.uint8) * 255
    if cv2.countNonZero(body) < max(16, (h * w) // 20):
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, kernel, iterations=1)
    return body


def effective_template_mask(
    gray_tpl: np.ndarray,
    alpha_mask: Optional[np.ndarray],
    *,
    allow_derived_body: bool = True,
) -> Optional[np.ndarray]:
    """Prefer PNG alpha; optionally derive body mask for large playspace templates."""
    if alpha_mask is not None and cv2.countNonZero(alpha_mask) >= 16:
        return alpha_mask
    if allow_derived_body:
        return body_mask_from_template_gray(gray_tpl)
    return None


def filter_peaks_by_score_margin(
    peaks: Sequence[Peak],
    *,
    margin: Optional[float] = None,
) -> List[Peak]:
    """Drop weak peaks far below the best score (reduces lava glint clutter)."""
    if not peaks:
        return []
    m = margin if margin is not None else _env_float("EXODIA_SHAPE_SCORE_MARGIN", 0.08)
    best = max(p[2] for p in peaks)
    cutoff = best - m
    return [p for p in peaks if p[2] >= cutoff]
