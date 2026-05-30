"""
Full-client colored OCR for OSRS UI text.

Tiled Tesseract ``image_to_data`` with per-span HSV color classification.
``TextFinder.scan`` is the stream entry point on a ``FrameSnapshot``.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from bot_capture import FrameSnapshot
from bot_eyes import resolve_tesseract_cmd

Bbox = Tuple[int, int, int, int]

_COLOR_NAMES = (
    "green",
    "red",
    "yellow",
    "cyan",
    "orange",
    "white",
    "unknown",
)

_DEFAULT_HSV_PALETTE: Dict[str, List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]] = {
    "green": [((35, 60, 80), (95, 255, 255))],
    # OSRS skilling "NOT fishing" — measured ~#CC0000–#EE0000 (HSV H≈0 S≈240–255).
    "red": [
        ((0, 180, 120), (12, 255, 255)),
        ((170, 180, 120), (179, 255, 255)),
    ],
    "yellow": [((12, 70, 100), (50, 255, 255))],
    "cyan": [((75, 70, 100), (110, 255, 255))],
    "orange": [((8, 100, 100), (18, 255, 255))],
    "white": [((0, 0, 180), (180, 60, 255))],
    "unknown": [],
}

_palette_cache: Optional[Dict[str, List[Tuple[np.ndarray, np.ndarray]]]] = None

# Measured on client "NOT fishing" UI (BGR): median #cd0101; clusters #c80000–#ee0000.
_OSRS_SKILLING_RED_LO = np.array([0, 0, 140], dtype=np.uint8)
_OSRS_SKILLING_RED_HI = np.array([60, 60, 255], dtype=np.uint8)
_OSRS_SKILLING_GREEN_LO = np.array([0, 140, 0], dtype=np.uint8)
_OSRS_SKILLING_GREEN_HI = np.array([60, 255, 60], dtype=np.uint8)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_hsv_pair(raw: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """``lower_h,s,v:upper_h,s,v`` (OpenCV hue 0–179)."""
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("expected lower:upper HSV pair, got %r" % raw)
    lower = tuple(int(x) for x in parts[0].split(","))
    upper = tuple(int(x) for x in parts[1].split(","))
    if len(lower) != 3 or len(upper) != 3:
        raise ValueError("HSV triple required in %r" % raw)
    return lower, upper


def _load_palette_from_env() -> Dict[str, List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]]:
    out: Dict[str, List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]] = {
        k: [tuple(p) for p in v] for k, v in _DEFAULT_HSV_PALETTE.items()
    }
    raw_json = os.environ.get("EXODIA_TEXT_COLOR_JSON", "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError("EXODIA_TEXT_COLOR_JSON is invalid JSON") from exc
        if isinstance(parsed, dict):
            for name, spec in parsed.items():
                key = str(name).strip().lower()
                if key not in _COLOR_NAMES:
                    continue
                ranges: List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = []
                if isinstance(spec, dict) and "lower" in spec and "upper" in spec:
                    lo = tuple(int(x) for x in spec["lower"])
                    hi = tuple(int(x) for x in spec["upper"])
                    ranges.append((lo, hi))
                elif isinstance(spec, list):
                    for item in spec:
                        if isinstance(item, dict) and "lower" in item and "upper" in item:
                            lo = tuple(int(x) for x in item["lower"])
                            hi = tuple(int(x) for x in item["upper"])
                            ranges.append((lo, hi))
                        elif isinstance(item, (list, tuple)) and len(item) == 2:
                            lo = tuple(int(x) for x in item[0])
                            hi = tuple(int(x) for x in item[1])
                            ranges.append((lo, hi))
                if ranges:
                    out[key] = ranges
    for name in _COLOR_NAMES:
        if name == "unknown":
            continue
        env_key = "EXODIA_TEXT_HSV_%s" % name.upper()
        env_val = os.environ.get(env_key, "").strip()
        if env_val:
            out[name] = [_parse_hsv_pair(env_val)]
    return out


def _compiled_palette() -> Dict[str, List[Tuple[np.ndarray, np.ndarray]]]:
    global _palette_cache
    if _palette_cache is not None:
        return _palette_cache
    raw = _load_palette_from_env()
    compiled: Dict[str, List[Tuple[np.ndarray, np.ndarray]]] = {}
    for name, ranges in raw.items():
        if not ranges:
            continue
        compiled[name] = [
            (np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8)) for lo, hi in ranges
        ]
    _palette_cache = compiled
    return compiled


def _configure_tesseract() -> None:
    pytesseract.pytesseract.tesseract_cmd = resolve_tesseract_cmd()


_configure_tesseract()


@dataclass(frozen=True)
class ColoredTextSpan:
    text: str
    color: str
    bbox: Bbox
    conf: float
    source: str


@dataclass(frozen=True)
class ClientTextSnapshot:
    spans: Tuple[ColoredTextSpan, ...]
    processed_seq: int
    capture_seq: int
    client_size: Tuple[int, int]
    elapsed_ms: float


@dataclass(frozen=True)
class OcrWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float


def text_min_conf() -> float:
    return _env_float("EXODIA_TEXT_MIN_CONF", 60.0)


def text_max_spans() -> int:
    return max(1, _env_int("EXODIA_TEXT_MAX_SPANS", 400))


def text_tile_min_variance() -> float:
    return _env_float("EXODIA_TEXT_TILE_MIN_VAR", 120.0)


def run_ocr_data(
    roi_bgr: np.ndarray,
    psm: Optional[int] = None,
    scale: Optional[float] = None,
    whitelist: Optional[str] = None,
) -> List[OcrWord]:
    """
    Tesseract ``image_to_data`` on a BGR ROI; box coords are in original ROI pixels.
    """
    if roi_bgr is None or not getattr(roi_bgr, "size", 0):
        return []
    img = roi_bgr
    inv_scale = 1.0
    if scale is not None and 0 < scale < 1.0:
        inv_scale = 1.0 / scale
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    parts: List[str] = []
    if psm is not None:
        parts.append("--psm %d" % int(psm))
    if whitelist:
        parts.append("-c tessedit_char_whitelist=%s" % whitelist)
    config = " ".join(parts)
    data = pytesseract.image_to_data(img, config=config, output_type=Output.DICT)
    min_conf = text_min_conf()
    words: List[OcrWord] = []
    n = len(data.get("text", []))
    for i in range(n):
        try:
            level = int(data["level"][i])
        except (TypeError, ValueError):
            continue
        if level != 5:
            continue
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0 or conf < min_conf:
            continue
        left = int(round(int(data["left"][i]) * inv_scale))
        top = int(round(int(data["top"][i]) * inv_scale))
        width = max(1, int(round(int(data["width"][i]) * inv_scale)))
        height = max(1, int(round(int(data["height"][i]) * inv_scale)))
        if width * height < 4:
            continue
        words.append(
            OcrWord(
                text=text,
                left=left,
                top=top,
                width=width,
                height=height,
                conf=conf,
            )
        )
    return words


def _text_stroke_min_sat() -> int:
    return _env_int("EXODIA_TEXT_STROKE_MIN_S", 160)


def _text_stroke_min_val() -> int:
    return _env_int("EXODIA_TEXT_STROKE_MIN_V", 120)


def text_local_bg_enabled() -> bool:
    return _env_bool("EXODIA_TEXT_LOCAL_BG", True)


def _ui_stroke_masks(crop_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    High-saturation UI lettering masks (separates #CC0000 text from dull red terrain).
    """
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    h_ch = hsv[:, :, 0]
    s_ch = hsv[:, :, 1]
    v_ch = hsv[:, :, 2]
    min_s = _text_stroke_min_sat()
    min_v = _text_stroke_min_val()
    sat = (s_ch >= min_s) & (v_ch >= min_v)
    b = crop_bgr[:, :, 0]
    g = crop_bgr[:, :, 1]
    r = crop_bgr[:, :, 2]
    red_hue = (h_ch <= 12) | (h_ch >= 168)
    red_dom = (r > g + 20) & (r > b + 20)
    green_hue = (h_ch >= 35) & (h_ch <= 95)
    green_dom = (g > r + 20) & (g > b + 20)
    red_mask = (sat & red_hue & red_dom).astype(np.uint8) * 255
    green_mask = (sat & green_hue & green_dom).astype(np.uint8) * 255
    return red_mask, green_mask


def _foreground_mask(crop_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    bright = gray >= 140
    saturated = hsv[:, :, 1] >= 40
    # OSRS skilling red/green is high-saturation but not always bright in grayscale (#CC0000).
    colored_ui = (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 50)
    red_stroke, green_stroke = _ui_stroke_masks(crop_bgr)
    stroke = cv2.bitwise_or(red_stroke, green_stroke)
    return ((bright & saturated) | (gray >= 200) | colored_ui | (stroke > 0)).astype(np.uint8) * 255


def _text_color_pixels(crop_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Prefer R- or G-dominant pixels so olive panel chrome does not skew the median."""
    pixels = crop_bgr[mask > 0]
    if pixels is None or len(pixels) < 3:
        return pixels
    r_dom = pixels[(pixels[:, 2] > pixels[:, 1] + 15) & (pixels[:, 2] > pixels[:, 0] + 15)]
    g_dom = pixels[(pixels[:, 1] > pixels[:, 2] + 15) & (pixels[:, 1] > pixels[:, 0] + 15)]
    if len(r_dom) >= max(3, int(len(pixels) * 0.12)):
        return r_dom
    if len(g_dom) >= max(3, int(len(pixels) * 0.12)):
        return g_dom
    return pixels


def _classify_osrs_skilling_bgr(crop_bgr: np.ndarray, mask: np.ndarray) -> str:
    """Direct BGR band for OSRS skilling status text (primary red / green)."""
    red_hit = cv2.bitwise_and(
        cv2.inRange(crop_bgr, _OSRS_SKILLING_RED_LO, _OSRS_SKILLING_RED_HI),
        mask,
    )
    green_hit = cv2.bitwise_and(
        cv2.inRange(crop_bgr, _OSRS_SKILLING_GREEN_LO, _OSRS_SKILLING_GREEN_HI),
        mask,
    )
    rc = int(cv2.countNonZero(red_hit))
    gc = int(cv2.countNonZero(green_hit))
    if rc >= 3 and rc >= gc:
        return "red"
    if gc >= 3 and gc > rc:
        return "green"
    return "unknown"


def _classify_span_color_bgr(crop_bgr: np.ndarray, mask: np.ndarray) -> str:
    """
    BGR heuristic for OSRS skilling lines (primary red #CC0000, not salmon).
    """
    osrs = _classify_osrs_skilling_bgr(crop_bgr, mask)
    if osrs != "unknown":
        return osrs
    pixels = _text_color_pixels(crop_bgr, mask)
    if pixels is None or len(pixels) < 3:
        return "unknown"
    b = pixels[:, 0].astype(np.float32)
    g = pixels[:, 1].astype(np.float32)
    r = pixels[:, 2].astype(np.float32)
    r_m = float(np.median(r))
    g_m = float(np.median(g))
    b_m = float(np.median(b))
    if g_m >= 180 and g_m > r_m + 35 and g_m > b_m + 35:
        return "green"
    if r_m >= 140 and r_m > g_m + 25 and r_m > b_m + 25:
        return "red"
    return "unknown"


def _classify_span_color_hsv(crop_bgr: np.ndarray, mask: np.ndarray) -> str:
    h, w = crop_bgr.shape[:2]
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    palette = _compiled_palette()
    best_name = "unknown"
    best_count = 0
    for name in _COLOR_NAMES:
        if name == "unknown":
            continue
        ranges = palette.get(name)
        if not ranges:
            continue
        combined = np.zeros((h, w), dtype=np.uint8)
        for lo, hi in ranges:
            combined = cv2.bitwise_or(combined, cv2.inRange(hsv, lo, hi))
        hit = cv2.bitwise_and(combined, mask)
        count = int(cv2.countNonZero(hit))
        if count > best_count:
            best_count = count
            best_name = name
    min_px = max(2, int(cv2.countNonZero(mask) * 0.06))
    if best_count < min_px:
        return "unknown"
    return best_name


def _classify_span_color_local(context_bgr: np.ndarray, inner: Bbox) -> str:
    """
    Compare OCR word interior to a nearby background ring.

    Picks high-saturation UI strokes inside the word box so red lava behind a
    transparent skilling panel does not dominate the median.
    """
    h0, w0 = context_bgr.shape[:2]
    ix, iy, iw, ih = (int(inner[i]) for i in range(4))
    if iw <= 0 or ih <= 0:
        return "unknown"
    pad = max(2, min(iw, ih) // 2)
    inner_m = np.zeros((h0, w0), dtype=np.uint8)
    cv2.rectangle(inner_m, (ix, iy), (ix + iw, iy + ih), 255, -1)
    outer_m = np.zeros((h0, w0), dtype=np.uint8)
    cv2.rectangle(
        outer_m,
        (max(0, ix - pad), max(0, iy - pad)),
        (min(w0, ix + iw + pad), min(h0, iy + ih + pad)),
        255,
        -1,
    )
    ring_m = cv2.subtract(outer_m, inner_m)
    red_stroke, green_stroke = _ui_stroke_masks(context_bgr)
    red_inner = cv2.bitwise_and(red_stroke, inner_m)
    green_inner = cv2.bitwise_and(green_stroke, inner_m)
    rc = int(cv2.countNonZero(red_inner))
    gc = int(cv2.countNonZero(green_inner))
    if rc < 2 and gc < 2:
        return "unknown"

    ring_n = int(cv2.countNonZero(ring_m))
    if ring_n >= 5:
        fg_red = context_bgr[red_inner > 0]
        bg = context_bgr[ring_m > 0]
        if len(fg_red) >= 2 and len(bg) >= 5:
            fg_r = float(np.median(fg_red[:, 2]))
            bg_r = float(np.median(bg[:, 2]))
            fg_g = float(np.median(fg_red[:, 1]))
            bg_g = float(np.median(bg[:, 1]))
            hsv_fg = cv2.cvtColor(fg_red.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
            hsv_bg = cv2.cvtColor(bg.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
            fg_s = float(np.median(hsv_fg[:, 1]))
            bg_s = float(np.median(hsv_bg[:, 1]))
            red_fg = (
                rc >= gc
                and fg_r >= bg_r + 25
                and fg_g <= bg_g + 15
                and fg_s >= bg_s + 25
            )
            if red_fg:
                return "red"
        if gc >= 2 and gc > rc:
            fg_gr = context_bgr[green_inner > 0]
            if len(fg_gr) >= 2 and ring_n >= 5 and len(bg) >= 5:
                if float(np.median(fg_gr[:, 1])) > float(np.median(bg[:, 1])) + 25:
                    return "green"
            elif gc >= 3:
                return "green"

    if rc >= 3 and rc >= gc:
        return "red"
    if gc >= 3 and gc > rc:
        return "green"
    return "unknown"


def classify_span_color(
    crop_bgr: np.ndarray,
    mask: Optional[np.ndarray] = None,
    *,
    bbox: Optional[Bbox] = None,
) -> str:
    """
    Classify UI text color from a word crop using HSV palette + OSRS BGR heuristics.

    When ``bbox`` lies inside a larger ``crop_bgr`` (padded tile context), local
    background-ring + high-saturation stroke masks run first to reject red terrain.
    """
    if crop_bgr is None or not getattr(crop_bgr, "size", 0):
        return "unknown"
    h, w = crop_bgr.shape[:2]
    inner_bbox: Optional[Bbox] = None
    word_crop = crop_bgr
    if bbox is not None and len(bbox) == 4:
        x, y, bw, bh = (int(bbox[i]) for i in range(4))
        area_ratio = (bw * bh) / max(1, h * w)
        has_margin = x > 0 or y > 0 or (x + bw) < w or (y + bh) < h
        if text_local_bg_enabled() and has_margin and area_ratio < 0.82:
            local = _classify_span_color_local(crop_bgr, (x, y, bw, bh))
            if local != "unknown":
                return local
        else:
            x1 = max(0, min(w, x))
            y1 = max(0, min(h, y))
            x2 = max(x1, min(w, x + bw))
            y2 = max(y1, min(h, y + bh))
            sub = crop_bgr[y1:y2, x1:x2]
            if sub.size == 0:
                return "unknown"
            word_crop = sub
    h, w = word_crop.shape[:2]
    if mask is None:
        mask = _foreground_mask(word_crop)
    elif mask.shape[:2] != (h, w):
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    if cv2.countNonZero(mask) < 2:
        mask = _foreground_mask(crop_bgr)
    if cv2.countNonZero(mask) < 2:
        mask = np.full((h, w), 255, dtype=np.uint8)

    osrs_name = _classify_osrs_skilling_bgr(word_crop, mask)
    if osrs_name != "unknown":
        return osrs_name
    bgr_name = _classify_span_color_bgr(word_crop, mask)
    if bgr_name != "unknown":
        return bgr_name
    hsv_name = _classify_span_color_hsv(word_crop, mask)
    if hsv_name != "unknown":
        return hsv_name
    return "unknown"


def _resolve_span_color(a: str, b: str) -> str:
    if a == b:
        return a
    if a == "unknown":
        return b
    if b == "unknown":
        return a
    return a


def _union_bbox(a: Bbox, b: Bbox) -> Bbox:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = min(ax, bx)
    y1 = min(ay, by)
    x2 = max(ax + aw, bx + bw)
    y2 = max(ay + ah, by + bh)
    return (x1, y1, x2 - x1, y2 - y1)


_NEUTRAL_MERGE_COLORS = frozenset({"white", "yellow", "orange", "unknown"})


def text_merge_max_gap_line_h() -> float:
    """Max horizontal gap between words, as a multiple of line height (chat lines need more)."""
    return max(1.0, _env_float("EXODIA_TEXT_MERGE_MAX_GAP_LINE_H", 12.0))


def text_merge_line_y_frac() -> float:
    """Vertical center tolerance when grouping words onto the same line."""
    return max(0.2, _env_float("EXODIA_TEXT_MERGE_LINE_Y_FRAC", 0.65))


def _colors_merge_compatible(a: str, b: str) -> bool:
    """Allow neutral UI/chat colors to chain; keep red/green/cyan distinct from each other."""
    ak, bk = a.lower(), b.lower()
    if ak == bk:
        return True
    if ak == "unknown" or bk == "unknown":
        return True
    if ak in _NEUTRAL_MERGE_COLORS and bk in _NEUTRAL_MERGE_COLORS:
        return True
    return False


def _should_merge_spans(a: ColoredTextSpan, b: ColoredTextSpan) -> bool:
    """Merge OCR words on the same UI line (e.g. ``Not`` + ``fishing``)."""
    ax, ay, aw, ah = a.bbox
    bx, by, bw, bh = b.bbox
    line_h = max(ah, bh, 1)
    acy = ay + ah * 0.5
    bcy = by + bh * 0.5
    y_frac = text_merge_line_y_frac()
    if abs(acy - bcy) > line_h * y_frac:
        return False
    gap = bx - (ax + aw)
    max_gap = line_h * text_merge_max_gap_line_h()
    if gap > max_gap:
        return False
    if gap < -line_h * 0.6:
        return False
    if not _colors_merge_compatible(a.color, b.color):
        return False
    return True


def _merge_two_spans(a: ColoredTextSpan, b: ColoredTextSpan) -> ColoredTextSpan:
    sep = "" if a.text.endswith(" ") or b.text.startswith(" ") else " "
    conf = min(a.conf, b.conf) if a.conf > 0 and b.conf > 0 else max(a.conf, b.conf)
    return ColoredTextSpan(
        text=a.text + sep + b.text,
        color=_resolve_span_color(a.color, b.color),
        bbox=_union_bbox(a.bbox, b.bbox),
        conf=conf,
        source=a.source,
    )


def _line_center_y(spans: Sequence[ColoredTextSpan]) -> float:
    return sum(s.bbox[1] + s.bbox[3] * 0.5 for s in spans) / max(1, len(spans))


def _line_height(spans: Sequence[ColoredTextSpan]) -> int:
    return max(max(s.bbox[3] for s in spans), 1)


def _group_spans_by_line(spans: Sequence[ColoredTextSpan]) -> List[List[ColoredTextSpan]]:
    """Cluster OCR words onto horizontal lines before chaining."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0]))
    y_frac = text_merge_line_y_frac()
    lines: List[List[ColoredTextSpan]] = [[ordered[0]]]
    for span in ordered[1:]:
        line = lines[-1]
        ref_y = _line_center_y(line)
        line_h = _line_height(line)
        span_cy = span.bbox[1] + span.bbox[3] * 0.5
        if abs(span_cy - ref_y) <= line_h * y_frac:
            line.append(span)
        else:
            lines.append([span])
    return lines


def _merge_line_spans(line: Sequence[ColoredTextSpan]) -> List[ColoredTextSpan]:
    """
    Greedily extend each span while the next word continues the same line.

    Uses a running merged bbox so gap checks reflect accumulated width.
    """
    ordered = sorted(line, key=lambda s: s.bbox[0])
    if not ordered:
        return []
    merged: List[ColoredTextSpan] = []
    idx = 0
    while idx < len(ordered):
        accum = ordered[idx]
        j = idx + 1
        while j < len(ordered) and _should_merge_spans(accum, ordered[j]):
            accum = _merge_two_spans(accum, ordered[j])
            j += 1
        merged.append(accum)
        idx = j
    return merged


def merge_adjacent_spans(spans: List[ColoredTextSpan]) -> List[ColoredTextSpan]:
    """Join per-word OCR boxes into line-length phrases."""
    if len(spans) < 2:
        return spans
    out: List[ColoredTextSpan] = []
    for line in _group_spans_by_line(spans):
        out.extend(_merge_line_spans(line))
    return out


def text_merge_words_enabled() -> bool:
    return _env_bool("EXODIA_TEXT_MERGE_WORDS", True)


def text_output_filter_enabled() -> bool:
    """Optional ``/meta`` span filter only — never applied to ``TextPerceptionCache``."""
    return _env_bool("EXODIA_TEXT_OUTPUT_FILTER", False)


def text_output_min_conf() -> float:
    return _env_float("EXODIA_TEXT_OUTPUT_MIN_CONF", 60.0)


def _bbox_intersects(a: Bbox, rect: Sequence[int]) -> bool:
    ax, ay, aw, ah = (int(a[i]) for i in range(4))
    rx, ry, rw, rh = (int(rect[i]) for i in range(4))
    ax2, ay2 = ax + aw, ay + ah
    rx2, ry2 = rx + rw, ry + rh
    ix1 = max(ax, rx)
    iy1 = max(ay, ry)
    ix2 = min(ax2, rx2)
    iy2 = min(ay2, ry2)
    return ix2 > ix1 and iy2 > iy1


def _pad_rect(rect: Sequence[int], frame_w: int, frame_h: int, *, pad_x: int, pad_y: int) -> Bbox:
    x, y, w, h = (int(rect[i]) for i in range(4))
    return _clamp_bbox([x - pad_x, y - pad_y, w + 2 * pad_x, h + 2 * pad_y], frame_w, frame_h)


def _clamp_bbox(rect: Sequence[int], frame_w: int, frame_h: int) -> Bbox:
    x, y, w, h = (int(rect[i]) for i in range(4))
    x = max(0, min(x, max(0, frame_w - 1)))
    y = max(0, min(y, max(0, frame_h - 1)))
    w = max(1, min(w, frame_w - x))
    h = max(1, min(h, frame_h - y))
    return (x, y, w, h)


def _output_keep_rois(
    frame_w: int,
    frame_h: int,
    *,
    action_strip_rect: Optional[Sequence[int]] = None,
) -> List[Bbox]:
    """UI bands where skilling / action-line text is expected (not playspace NPC labels)."""
    rois: List[Bbox] = []
    if action_strip_rect is not None and len(action_strip_rect) == 4:
        rois.append(
            _pad_rect(action_strip_rect, frame_w, frame_h, pad_x=28, pad_y=14)
        )
    rois.append(
        _clamp_bbox(
            [
                max(0, int(frame_w * 0.34)),
                max(0, int(frame_h * 0.40)),
                max(120, int(frame_w * 0.66)),
                max(80, int(frame_h * 0.58)),
            ],
            frame_w,
            frame_h,
        )
    )
    rois.append(
        _clamp_bbox(
            [0, max(0, int(frame_h * 0.30)), max(120, int(frame_w * 0.38)), max(60, int(frame_h * 0.35))],
            frame_w,
            frame_h,
        )
    )
    return rois


def _span_in_keep_rois(span: ColoredTextSpan, rois: Sequence[Bbox]) -> bool:
    return any(_bbox_intersects(span.bbox, roi) for roi in rois)


def _normalize_span_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _span_is_green_fishing(span: ColoredTextSpan) -> bool:
    """Green ``Fishing`` (optional meta filter helper; cache keeps all spans)."""
    norm = _normalize_span_text(span.text)
    if not norm or "fish" not in norm:
        return False
    if re.search(r"\bnot\b", norm):
        return False
    return span.color.lower() == "green"


def filter_spans_for_output(
    spans: Sequence[ColoredTextSpan],
    client_bgr: np.ndarray,
    *,
    frame_w: int,
    frame_h: int,
    action_strip_rect: Optional[Sequence[int]] = None,
) -> List[ColoredTextSpan]:
    """Optional meta/UI subset — full OCR remains in ``TextPerceptionCache``."""
    _ = client_bgr
    if not spans:
        return []
    if not text_output_filter_enabled():
        return list(spans)
    rois = _output_keep_rois(frame_w, frame_h, action_strip_rect=action_strip_rect)
    kept: List[ColoredTextSpan] = []
    for span in spans:
        if span.conf < text_output_min_conf():
            continue
        if not _span_is_green_fishing(span):
            continue
        if not _span_in_keep_rois(span, rois):
            continue
        kept.append(span)
    return kept


def _bbox_iou(a: Bbox, b: Bbox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _dedupe_spans(spans: List[ColoredTextSpan]) -> List[ColoredTextSpan]:
    if not spans:
        return []
    iou_thresh = _env_float("EXODIA_TEXT_DEDUPE_IOU", 0.45)
    spans_sorted = sorted(spans, key=lambda s: (-s.conf, s.bbox[1], s.bbox[0]))
    kept: List[ColoredTextSpan] = []
    for cand in spans_sorted:
        ct = _normalize_text(cand.text)
        duplicate = False
        for prev in kept:
            pt = _normalize_text(prev.text)
            if ct != pt and ct not in pt and pt not in ct:
                continue
            if _bbox_iou(cand.bbox, prev.bbox) >= iou_thresh:
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
    return kept


def _tile_active(tile_bgr: np.ndarray, min_var: float) -> bool:
    if tile_bgr is None or not getattr(tile_bgr, "size", 0):
        return False
    gray = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.var(gray)) >= min_var


def scan_client_text(
    client_bgr: np.ndarray,
    *,
    tile_px: int = 256,
    overlap: int = 32,
    processed_seq: int = 0,
    capture_seq: int = 0,
    psm: Optional[int] = None,
    scale: Optional[float] = None,
    whitelist: Optional[str] = None,
) -> ClientTextSnapshot:
    """
    Tile the full client frame, OCR active tiles, classify color, dedupe, and cap spans.

    All qualifying spans are stored in the cache; fishing bots filter for green
    ``Fishing`` when reading (see ``bot_text_query``).
    """
    t0 = time.monotonic()
    if client_bgr is None or not getattr(client_bgr, "size", 0):
        return ClientTextSnapshot(
            spans=(),
            processed_seq=int(processed_seq),
            capture_seq=int(capture_seq),
            client_size=(0, 0),
            elapsed_ms=0.0,
        )
    h0, w0 = client_bgr.shape[:2]
    tile_px = max(64, int(tile_px))
    overlap = max(0, min(overlap, tile_px - 8))
    step = max(8, tile_px - overlap)
    min_var = text_tile_min_variance()
    psm_eff = psm if psm is not None else _env_int("EXODIA_TEXT_PSM", 11)
    scale_eff = scale
    if scale_eff is None:
        raw_scale = os.environ.get("EXODIA_TEXT_OCR_SCALE", "").strip()
        if raw_scale:
            try:
                scale_eff = float(raw_scale)
            except ValueError:
                scale_eff = None
    spans: List[ColoredTextSpan] = []
    ty_idx = 0
    for y0 in range(0, h0, step):
        tx_idx = 0
        for x0 in range(0, w0, step):
            tw = min(tile_px, w0 - x0)
            th = min(tile_px, h0 - y0)
            tile = client_bgr[y0 : y0 + th, x0 : x0 + tw]
            source = "tile_%d_%d" % (tx_idx, ty_idx)
            tx_idx += 1
            if not _tile_active(tile, min_var):
                continue
            for word in run_ocr_data(tile, psm=psm_eff, scale=scale_eff, whitelist=whitelist):
                gx = x0 + word.left
                gy = y0 + word.top
                bbox: Bbox = (gx, gy, word.width, word.height)
                pad = max(4, int(min(word.width, word.height) * 0.65))
                cx1 = max(0, word.left - pad)
                cy1 = max(0, word.top - pad)
                cx2 = min(tw, word.left + word.width + pad)
                cy2 = min(th, word.top + word.height + pad)
                ctx = tile[cy1:cy2, cx1:cx2]
                inner: Bbox = (
                    word.left - cx1,
                    word.top - cy1,
                    word.width,
                    word.height,
                )
                color = classify_span_color(ctx, bbox=inner)
                spans.append(
                    ColoredTextSpan(
                        text=word.text,
                        color=color,
                        bbox=bbox,
                        conf=word.conf,
                        source=source,
                    )
                )
        ty_idx += 1
    deduped = _dedupe_spans(spans)
    if text_merge_words_enabled():
        deduped = merge_adjacent_spans(deduped)
    cap = text_max_spans()
    if len(deduped) > cap:
        deduped = sorted(deduped, key=lambda s: -s.conf)[:cap]
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    return ClientTextSnapshot(
        spans=tuple(deduped),
        processed_seq=int(processed_seq),
        capture_seq=int(capture_seq),
        client_size=(int(w0), int(h0)),
        elapsed_ms=float(elapsed_ms),
    )


class TextFinder:
    """Full-client colored OCR on a dispatched ``FrameSnapshot``."""

    @staticmethod
    def scan(snap: FrameSnapshot) -> ClientTextSnapshot:
        seq = int(getattr(snap, "seq", 0) or 0)
        return scan_client_text(
            snap.bgr,
            processed_seq=seq,
            capture_seq=seq,
        )


__all__ = [
    "Bbox",
    "ClientTextSnapshot",
    "ColoredTextSpan",
    "OcrWord",
    "TextFinder",
    "classify_span_color",
    "merge_adjacent_spans",
    "run_ocr_data",
    "text_local_bg_enabled",
    "text_merge_line_y_frac",
    "text_merge_max_gap_line_h",
    "text_merge_words_enabled",
    "filter_spans_for_output",
    "scan_client_text",
    "text_max_spans",
    "text_min_conf",
    "text_output_filter_enabled",
]
