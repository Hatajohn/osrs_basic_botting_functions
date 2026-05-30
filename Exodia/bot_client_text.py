"""
Full-client colored OCR for OSRS UI text.

Tiled Tesseract ``image_to_data`` with per-span HSV color classification.
``TextFinder.scan`` is the stream entry point on a ``FrameSnapshot``.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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
    return _env_float("EXODIA_TEXT_MIN_CONF", 40.0)


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


def _foreground_mask(crop_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    bright = gray >= 140
    saturated = hsv[:, :, 1] >= 40
    # OSRS skilling red/green is high-saturation but not always bright in grayscale (#CC0000).
    colored_ui = (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 50)
    return ((bright & saturated) | (gray >= 200) | colored_ui).astype(np.uint8) * 255


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


def classify_span_color(
    crop_bgr: np.ndarray,
    mask: Optional[np.ndarray] = None,
    *,
    bbox: Optional[Bbox] = None,
) -> str:
    """
    Classify UI text color from a word crop using HSV palette + OSRS BGR heuristics.

    ``mask`` may be a same-size uint8 mask; if omitted, a bright/saturated foreground
    mask is built. ``bbox`` is accepted for API symmetry but ignored when ``mask`` is set.
    """
    if crop_bgr is None or not getattr(crop_bgr, "size", 0):
        return "unknown"
    h, w = crop_bgr.shape[:2]
    if mask is None and bbox is not None:
        x, y, bw, bh = bbox
        x1 = max(0, min(w, x))
        y1 = max(0, min(h, y))
        x2 = max(x1, min(w, x + bw))
        y2 = max(y1, min(h, y + bh))
        sub = crop_bgr[y1:y2, x1:x2]
        if sub.size == 0:
            return "unknown"
        crop_bgr = sub
        h, w = crop_bgr.shape[:2]
    if mask is None:
        mask = _foreground_mask(crop_bgr)
    elif mask.shape[:2] != (h, w):
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    if cv2.countNonZero(mask) < 2:
        mask = _foreground_mask(crop_bgr)
    if cv2.countNonZero(mask) < 2:
        mask = np.full((h, w), 255, dtype=np.uint8)

    osrs_name = _classify_osrs_skilling_bgr(crop_bgr, mask)
    if osrs_name != "unknown":
        return osrs_name
    bgr_name = _classify_span_color_bgr(crop_bgr, mask)
    if bgr_name != "unknown":
        return bgr_name
    hsv_name = _classify_span_color_hsv(crop_bgr, mask)
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


def _should_merge_spans(a: ColoredTextSpan, b: ColoredTextSpan) -> bool:
    """Merge OCR words on the same UI line (e.g. ``Not`` + ``fishing``)."""
    ax, ay, aw, ah = a.bbox
    bx, by, bw, bh = b.bbox
    line_h = max(ah, bh, 1)
    acy = ay + ah * 0.5
    bcy = by + bh * 0.5
    if abs(acy - bcy) > line_h * 0.55:
        return False
    gap = bx - (ax + aw)
    if gap > line_h * 4.0:
        return False
    if gap < -line_h * 0.6:
        return False
    if (
        a.color != b.color
        and a.color != "unknown"
        and b.color != "unknown"
    ):
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


def merge_adjacent_spans(spans: List[ColoredTextSpan]) -> List[ColoredTextSpan]:
    """Join per-word OCR boxes that belong to one phrase on the same line."""
    if len(spans) < 2:
        return spans
    ordered = sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0]))
    merged: List[ColoredTextSpan] = [ordered[0]]
    for span in ordered[1:]:
        prev = merged[-1]
        if _should_merge_spans(prev, span):
            merged[-1] = _merge_two_spans(prev, span)
        else:
            merged.append(span)
    return merged


def text_merge_words_enabled() -> bool:
    return _env_bool("EXODIA_TEXT_MERGE_WORDS", True)


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
                x1, y1 = word.left, word.top
                x2 = min(tw, x1 + word.width)
                y2 = min(th, y1 + word.height)
                crop = tile[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else tile
                color = classify_span_color(crop)
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
    "text_merge_words_enabled",
    "scan_client_text",
    "text_max_spans",
    "text_min_conf",
]
