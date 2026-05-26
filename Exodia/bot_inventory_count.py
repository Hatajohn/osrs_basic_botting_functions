"""
Legacy template-match inventory counting (diagnose / calibration only).

Production bots should use ``read_inventory_labels`` +
``count_labeled_item_slots`` from ``bot_inventory_items`` (see infernal and sacred
eel fishing). This module remains for template-threshold tuning: per-slot icon
match, stack-quantity OCR, and full-panel peak fallback.
"""
from __future__ import annotations

import math
import os
import warnings
import re
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_eyes import (
    INV_COLS,
    INV_ROWS,
    _load_template_gray,
    _parse_csv_bgr_tag,
    analyze_inventory_panel_occupancy,
    inventory_grid_cell_xywh,
    run_ocr,
)

if TYPE_CHECKING:
    import bot_eyes as Eyes


def _default_threshold() -> float:
    from bot_env import env_float_any

    return env_float_any(0.28, "EXO_INV_CNT_THR", "EXODIA_INV_TEMPLATE_THRESHOLD")


def _cell_inset_px() -> int:
    return max(0, int(os.environ.get("EXODIA_INV_CELL_INSET", "2")))


def _runelite_tag_mask(hsv: np.ndarray) -> np.ndarray:
    """
    Pixels to ignore for template match — RuneLite item highlights (green / yellow / cyan).

    Yellow ground-item tags are masked; stack-count band is median-filled separately.
    """
    green = cv2.inRange(hsv, (35, 80, 80), (95, 255, 255))
    yellow = cv2.inRange(hsv, (12, 70, 100), (50, 255, 255))
    cyan = cv2.inRange(hsv, (75, 70, 100), (110, 255, 255))
    return cv2.bitwise_or(green, cv2.bitwise_or(yellow, cyan))


def _mask_runelite_tags_in_gray(gray: np.ndarray, hsv: np.ndarray) -> np.ndarray:
    tag_mask = _runelite_tag_mask(hsv)
    if cv2.countNonZero(tag_mask) <= 0:
        return gray
    fill = int(np.median(gray[tag_mask == 0])) if np.any(tag_mask == 0) else 90
    out = gray.copy()
    out[tag_mask > 0] = fill
    return out


def _strip_runelite_tags_bgr(cell_bgr: np.ndarray) -> np.ndarray:
    """Median-fill RuneLite highlight pixels in BGR (for cleaner saved templates)."""
    if cell_bgr is None or cell_bgr.size == 0:
        return cell_bgr
    hsv = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2HSV)
    tag_mask = _runelite_tag_mask(hsv)
    if cv2.countNonZero(tag_mask) <= 0:
        return cell_bgr
    out = cell_bgr.copy()
    fill = np.median(out[tag_mask == 0], axis=0).astype(np.uint8) if np.any(tag_mask == 0) else np.array(
        (32, 42, 52), dtype=np.uint8
    )
    out[tag_mask > 0] = fill
    return out


def _inventory_plate_bgr() -> np.ndarray:
    """Typical OSRS inventory slot plate color (BGR)."""
    fb = _parse_csv_bgr_tag("EXODIA_INV_FALLBACK_EMPTY_BGR")
    if fb is not None:
        return np.array(fb, dtype=np.float32)
    return np.array([41.0, 53.0, 62.0], dtype=np.float32)


def _inventory_plate_max_delta() -> float:
    return float(os.environ.get("EXODIA_INV_EMPTY_BGR_MAX_DELTA", "12"))


def inventory_plate_background_mask(
    cell_bgr: np.ndarray,
    *,
    plate_bgr: Optional[np.ndarray] = None,
    max_delta: Optional[float] = None,
) -> np.ndarray:
    """
    True where ``cell_bgr`` pixel matches the inventory slot plate background.

    Uses the same BGR delta test as empty-slot detection in ``analyze_inventory_panel_occupancy``.
    """
    if cell_bgr is None or cell_bgr.size == 0:
        return np.zeros((0, 0), dtype=bool)
    plate = plate_bgr if plate_bgr is not None else _inventory_plate_bgr()
    delta_cap = max_delta if max_delta is not None else _inventory_plate_max_delta()
    lb = _parse_csv_bgr_tag("EXODIA_INV_EMPTY_BGR_LOWER")
    ub = _parse_csv_bgr_tag("EXODIA_INV_EMPTY_BGR_UPPER")

    mu = cell_bgr.astype(np.float32)
    color_delta = np.max(np.abs(mu - plate.reshape(1, 1, 3)), axis=2)
    bg = color_delta <= delta_cap
    if lb is not None and ub is not None:
        lo = np.array(lb, dtype=np.float32)
        hi = np.array(ub, dtype=np.float32)
        bg &= np.all((mu >= lo) & (mu <= hi), axis=2)
    return bg


def strip_inventory_plate_background(
    cell_bgr: np.ndarray,
    *,
    crop: Optional[bool] = None,
) -> np.ndarray:
    """
    Remove inventory plate pixels; return BGRA with transparent background.

    When ``crop`` is true (default), tight-crop to the icon bounding box with 1px pad.
    Set ``EXODIA_ITEM_STRIP_CROP=0`` to keep the original slot dimensions instead.
    """
    if cell_bgr is None or cell_bgr.size == 0:
        return cell_bgr
    if cell_bgr.ndim == 3 and cell_bgr.shape[2] == 4:
        cell_bgr = cell_bgr[:, :, :3]

    clean = _strip_runelite_tags_bgr(cell_bgr)
    bg = inventory_plate_background_mask(clean)
    fg = ~bg
    fg_u8 = fg.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    fg_u8 = cv2.morphologyEx(fg_u8, cv2.MORPH_CLOSE, kernel)
    fg_u8 = cv2.morphologyEx(fg_u8, cv2.MORPH_OPEN, kernel)
    fg = fg_u8 > 0

    if not np.any(fg):
        bgra = cv2.cvtColor(clean, cv2.COLOR_BGR2BGRA)
        bgra[:, :, 3] = 255
        return bgra

    alpha = np.where(fg, 255, 0).astype(np.uint8)
    bgra = cv2.cvtColor(clean, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = alpha

    if crop is None:
        crop = os.environ.get("EXODIA_ITEM_STRIP_CROP", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
    if not crop:
        return bgra

    ys, xs = np.where(fg)
    pad = 1
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(bgra.shape[0], int(ys.max()) + pad + 1)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(bgra.shape[1], int(xs.max()) + pad + 1)
    return bgra[y0:y1, x0:x1].copy()


def bgra_to_match_bgr(bgra: np.ndarray) -> np.ndarray:
    """Composite transparent template/icon pixels onto the inventory plate for matching."""
    if bgra is None or bgra.size == 0:
        return bgra
    if bgra.ndim != 3 or bgra.shape[2] != 4:
        return bgra[:, :, :3] if bgra.ndim == 3 else bgra
    plate = _inventory_plate_bgr().astype(np.uint8)
    bgr = bgra[:, :, :3].astype(np.float32)
    alpha = bgra[:, :, 3].astype(np.float32) / 255.0
    out = np.empty_like(bgr)
    for c in range(3):
        out[:, :, c] = bgr[:, :, c] * alpha + float(plate[c]) * (1.0 - alpha)
    return out.astype(np.uint8)


def _normalize_slot_icon_gray(cell_bgr: np.ndarray) -> np.ndarray:
    """
    Center the item icon on a canonical slot canvas.

    Icons sit at different offsets slot-to-slot; normalization makes template
    match stable after moving items around the grid.
    """
    if cell_bgr is None or cell_bgr.size == 0:
        return cell_bgr
    h, w = cell_bgr.shape[:2]
    gray = _slot_gray_for_match(cell_bgr)
    hsv = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2HSV)
    y_band, x_band = _stack_band_rect(h, w)
    sat = hsv[:, :, 1]
    body = np.ones((h, w), dtype=bool)
    body[0:y_band, 0:x_band] = False
    plate_ref = int(np.median(gray[0:y_band, x_band:])) if y_band > 0 and x_band < w else int(np.median(gray))
    icon = body & (sat >= 28) & (gray > plate_ref + 6)
    if not np.any(icon):
        return gray
    ys, xs = np.where(icon)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    crop = gray[y0 : y1 + 1, x0 : x1 + 1]
    if crop.size == 0:
        return gray
    canvas = np.full((h, w), plate_ref, dtype=np.uint8)
    ih, iw = crop.shape[:2]
    cy = max(0, (h - ih) // 2)
    cx = max(0, (w - iw) // 2)
    canvas[cy : cy + ih, cx : cx + iw] = crop
    return canvas


def _panel_gray_for_match(panel_bgr: np.ndarray) -> np.ndarray:
    """Grayscale for full-panel template match (masks RuneLite item highlight tags)."""
    gray = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2HSV)
    return _mask_runelite_tags_in_gray(gray, hsv)


def _stack_band_rect(h: int, w: int) -> Tuple[int, int]:
    y1 = max(8, int(h * float(os.environ.get("EXODIA_INV_STACK_Y_FRAC", "0.42"))))
    x1 = max(8, int(w * float(os.environ.get("EXODIA_INV_STACK_X_FRAC", "0.50"))))
    return y1, x1


def _fill_stack_band_in_gray(gray: np.ndarray, y1: int, x1: int) -> np.ndarray:
    if y1 <= 0 and x1 <= 0:
        return gray
    out = gray.copy()
    band = out[0:y1, 0:x1]
    if band.size == 0:
        return out
    fill = int(np.median(out[y1:, x1:])) if out[y1:, x1:].size else int(np.median(out))
    out[0:y1, 0:x1] = fill
    return out


def _slot_gray_for_match(cell_bgr: np.ndarray) -> np.ndarray:
    """
    Grayscale for matching — masks RuneLite highlight tags (green / yellow / cyan).

    Optionally median-fills the stack-quantity band (``EXODIA_MATCH_STACK_MASK``).
    """
    gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2HSV)
    gray = _mask_runelite_tags_in_gray(gray, hsv)
    if os.environ.get("EXODIA_MATCH_STACK_MASK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        h, w = gray.shape[:2]
        y1, x1 = _stack_band_rect(h, w)
        gray = _fill_stack_band_in_gray(gray, y1, x1)
    return gray


def _slot_gray_slide_score(
    cell_bgr: np.ndarray,
    template_gray: np.ndarray,
    template_mask: Optional[np.ndarray] = None,
) -> float:
    """Sliding ``matchTemplate`` on tag-masked full-tile gray."""
    if cell_bgr is None or cell_bgr.size == 0 or template_gray is None:
        return 0.0
    gray = _slot_gray_for_match(cell_bgr)
    th, tw = template_gray.shape[:2]
    if gray.shape[0] < th or gray.shape[1] < tw:
        return 0.0
    if (
        template_mask is not None
        and template_mask.shape[:2] == template_gray.shape[:2]
        and cv2.countNonZero(template_mask) >= 16
    ):
        res = cv2.matchTemplate(
            gray, template_gray, cv2.TM_CCOEFF_NORMED, mask=template_mask
        )
    else:
        res = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return float(max_val)


def _normalized_icon_match_score(cell_bgr: np.ndarray, template_bgr: np.ndarray) -> float:
    """Compare icon-centered slot canvases (position-invariant)."""
    if cell_bgr is None or cell_bgr.size == 0 or template_bgr is None or template_bgr.size == 0:
        return 0.0
    q = _normalize_slot_icon_gray(cell_bgr)
    t = _normalize_slot_icon_gray(template_bgr)
    if q.shape != t.shape:
        return 0.0
    return float(cv2.matchTemplate(q, t, cv2.TM_CCOEFF_NORMED)[0, 0])


def _slot_template_score(cell_bgr: np.ndarray, template_gray: np.ndarray) -> float:
    return _slot_gray_slide_score(cell_bgr, template_gray)


def _stack_digit_roi(cell_bgr: np.ndarray) -> np.ndarray:
    """OSRS stack counts are drawn in the **top-left** of the slot (yellow digits)."""
    h, w = cell_bgr.shape[:2]
    y1 = max(8, int(h * float(os.environ.get("EXODIA_INV_STACK_Y_FRAC", "0.42"))))
    x1 = max(8, int(w * float(os.environ.get("EXODIA_INV_STACK_X_FRAC", "0.50"))))
    return cell_bgr[0:y1, 0:x1]


def _read_stack_quantity(cell_bgr: np.ndarray) -> int:
    """
    Parse the yellow stack number on an inventory slot (defaults to 1 if unreadable).
    """
    if cell_bgr is None or cell_bgr.size == 0:
        return 0
    roi = _stack_digit_roi(cell_bgr)
    if roi.size == 0:
        return 1
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (18, 80, 120), (40, 255, 255))
    if cv2.countNonZero(yellow) >= 8:
        masked = cv2.bitwise_and(roi, roi, mask=yellow)
        gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    scale = float(os.environ.get("EXODIA_INV_STACK_OCR_SCALE", "3"))
    big = cv2.resize(
        gray,
        (0, 0),
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )
    try:
        text = run_ocr(big, psm=7, whitelist="0123456789KkMm")
    except Exception:
        return 1
    text = text.replace(",", "").replace(" ", "")
    if not text:
        return 1
    m = re.search(r"(\d+)", text)
    if m:
        return max(1, min(2_147_483_647, int(m.group(1))))
    mult = 1
    num_part = text
    if text[-1:].lower() == "k":
        mult = 1000
        num_part = text[:-1]
    elif text[-1:].lower() == "m":
        mult = 1_000_000
        num_part = text[:-1]
    m = re.search(r"(\d+)", num_part)
    if m:
        return max(1, int(m.group(1)) * mult)
    return 1


def _peak_bbox_to_slot(
    panel: np.ndarray,
    px: int,
    py: int,
    tw: int,
    th: int,
    occ: Optional[List[List[bool]]],
) -> Tuple[int, int]:
    """Pick the grid slot with best IoU to the template peak (respects occupancy when set)."""
    h0, w0 = panel.shape[:2]
    pseudo: Tuple[int, int, int, int] = (0, 0, w0, h0)
    inset = _cell_inset_px()
    peak = (px, py, px + tw, py + th)
    best: Optional[Tuple[int, int]] = None
    best_iou = 0.0
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if occ is not None and not occ[row][col]:
                continue
            cell_xywh = inventory_grid_cell_xywh(pseudo, row, col, inset)
            if cell_xywh is None:
                continue
            sx, sy, sw, sh = cell_xywh
            slot = (sx, sy, sx + sw, sy + sh)
            ix0 = max(peak[0], slot[0])
            iy0 = max(peak[1], slot[1])
            ix1 = min(peak[2], slot[2])
            iy1 = min(peak[3], slot[3])
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            union = tw * th + sw * sh - inter
            iou = inter / union if union > 0 else 0.0
            if iou > best_iou:
                best_iou = iou
                best = (row, col)
    if best is not None and best_iou >= float(
        os.environ.get("EXODIA_INV_PEAK_SLOT_IOU_MIN", "0.05")
    ):
        return best
    return _peak_center_to_slot(panel.shape, px + tw // 2, py + th // 2)


def _match_inv_slot_peaks(
    res: np.ndarray,
    template_w: int,
    template_h: int,
    threshold: float,
    max_peaks: int = 40,
) -> List[Tuple[int, int, float]]:
    """
    Peak NMS sized for **one hit per inventory slot**, not one per template footprint.

    Default ``_match_template_peaks`` suppresses a full template-sized window, which leaves
    only ~one sacred eel match per column when icons are stacked vertically.
    """
    if res.size == 0:
        return []
    suppress_w = max(8, int(os.environ.get("EXODIA_INV_PEAK_SUPPRESS_W", "22")))
    suppress_h = max(8, int(os.environ.get("EXODIA_INV_PEAK_SUPPRESS_H", "16")))
    suppressed = res.astype(np.float64).copy()
    peaks: List[Tuple[int, int, float]] = []
    h_r, w_r = suppressed.shape[:2]
    for _ in range(max_peaks):
        _, max_val, _, max_loc = cv2.minMaxLoc(suppressed)
        if max_val < threshold or not math.isfinite(float(max_val)):
            break
        x, y = int(max_loc[0]), int(max_loc[1])
        peaks.append((x, y, float(max_val)))
        x0 = max(0, x - suppress_w // 2)
        y0 = max(0, y - suppress_h // 2)
        x1 = min(w_r, x + suppress_w)
        y1 = min(h_r, y + suppress_h)
        suppressed[y0:y1, x0:x1] = 0.0
    return peaks


def _peak_center_to_slot(panel_shape: Tuple[int, ...], cx: int, cy: int) -> Tuple[int, int]:
    """Map a template-match center in panel coords to ``(row, col)``."""
    h0, w0 = int(panel_shape[0]), int(panel_shape[1])
    cw = max(1, w0 // INV_COLS)
    ch = max(1, h0 // INV_ROWS)
    col = min(INV_COLS - 1, max(0, cx // cw))
    row = min(INV_ROWS - 1, max(0, cy // ch))
    return row, col


def _count_inventory_via_panel_peaks(
    panel: np.ndarray,
    template_gray: np.ndarray,
    thr: float,
) -> int:
    """
    Match on the full inventory crop, assign each peak to a grid slot, sum stack OCR.

    Tolerates small grid misalignment better than per-cell-only matching.
    """
    if panel is None or panel.size == 0 or template_gray is None:
        return 0
    gray = _panel_gray_for_match(panel)
    th, tw = template_gray.shape[:2]
    if gray.shape[0] < th or gray.shape[1] < tw:
        return 0
    res = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
    peaks = _match_inv_slot_peaks(res, tw, th, thr, max_peaks=40)
    if not peaks:
        return 0

    h0, w0 = panel.shape[:2]
    slot_sz = int(os.environ.get("EXODIA_INV_SLOT_SIZE", str(max(72, tw + 8, th + 8))))
    # One peak per slot (~36px row height); keep dedupe smaller than half a slot.
    dedupe_r = max(8, int(os.environ.get("EXODIA_INV_DEDUPE_RADIUS", "14")))
    centers: List[Tuple[int, int]] = []
    total = 0
    for px, py, score in peaks:
        if score < thr:
            continue
        cx = px + tw // 2
        cy = py + th // 2
        if any(math.hypot(cx - x, cy - y) < dedupe_r for x, y in centers):
            continue
        centers.append((cx, cy))
        x0 = max(0, min(cx - slot_sz // 2, w0 - slot_sz))
        y0 = max(0, min(cy - slot_sz // 2, h0 - slot_sz))
        cell = panel[y0 : y0 + slot_sz, x0 : x0 + slot_sz]
        total += _read_stack_quantity(cell)
    return total


def _dedupe_points(points: Sequence[Sequence[int]], radius_px: int) -> List[List[int]]:
    radius_px = max(1, int(radius_px))
    kept: List[List[int]] = []
    for pt in sorted(points, key=lambda p: (-p[0], p[1])):
        px, py = int(pt[0]), int(pt[1])
        if all(math.hypot(px - k[0], py - k[1]) >= radius_px for k in kept):
            kept.append([px, py])
    return kept


def count_inventory_stacks(
    eyes: "Eyes.BotEyes",
    template_filename: str,
    *,
    threshold: Optional[float] = None,
    dedupe_radius_px: Optional[int] = None,
    refresh_inventory: bool = False,
) -> int:
    """Question: How many distinct icon regions match this template (legacy; undercounts stacks)?"""
    if refresh_inventory:
        eyes.update()
    elif eyes.curr_inventory is None or getattr(eyes.curr_inventory, "size", 0) == 0:
        eyes.check_inventory()

    thr = _default_threshold() if threshold is None else threshold
    radius = int(os.environ.get("EXODIA_INV_DEDUPE_RADIUS", "18"))
    if dedupe_radius_px is not None:
        radius = dedupe_radius_px

    hits = eyes.locate_image(
        filename=template_filename,
        inv=True,
        name="count stacks %s" % template_filename,
        threshold=thr,
    )
    if not hits:
        return 0
    return len(_dedupe_points(hits, radius))


def count_inventory_objects(
    eyes: "Eyes.BotEyes",
    template_filename: str,
    *,
    threshold: Optional[float] = None,
    dedupe_radius_px: Optional[int] = None,
    refresh_inventory: bool = False,
    mode: Optional[str] = None,
) -> int:
    """Question: What is the total item count for this template (quantity or stacks mode)?"""
    count_mode = (mode or os.environ.get("EXODIA_INV_COUNT_MODE", "quantity")).strip().lower()
    if count_mode == "stacks":
        return count_inventory_stacks(
            eyes,
            template_filename,
            threshold=threshold,
            dedupe_radius_px=dedupe_radius_px,
            refresh_inventory=refresh_inventory,
        )
    return count_inventory_quantity(
        eyes,
        template_filename,
        threshold=threshold,
        refresh_inventory=refresh_inventory,
    )


def count_inventory_quantity(
    eyes: "Eyes.BotEyes",
    template_filename: str,
    *,
    threshold: Optional[float] = None,
    refresh_inventory: bool = False,
) -> int:
    """Question: What is the sum of stack OCR quantities for slots matching this template?"""
    if refresh_inventory:
        eyes.update()
    elif eyes.curr_inventory is None or getattr(eyes.curr_inventory, "size", 0) == 0:
        eyes.check_inventory()

    panel = eyes._inventory_panel_bgr_for_slots()
    if panel is None or panel.size == 0:
        return 0

    template_path = Path(os.getcwd()) / "images" / template_filename
    template_gray = _load_template_gray(str(template_path))
    if template_gray is None:
        return 0

    thr = _default_threshold() if threshold is None else float(threshold)
    thr_occ = float(os.environ.get("EXODIA_INV_OCC_SLOT_THR", "0.22"))
    inset = _cell_inset_px()
    h0, w0 = panel.shape[:2]
    pseudo_rect: Tuple[int, int, int, int] = (0, 0, w0, h0)
    occ, _, _ = analyze_inventory_panel_occupancy(panel)
    total = 0
    grid_slots: Dict[Tuple[int, int], int] = {}

    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if occ is not None and not occ[row][col]:
                continue
            cell_xywh = inventory_grid_cell_xywh(pseudo_rect, row, col, inset)
            if cell_xywh is None:
                continue
            sx, sy, sw, sh = cell_xywh
            cell = panel[sy : sy + sh, sx : sx + sw]
            score = _slot_template_score(cell, template_gray)
            if score < thr_occ:
                continue
            qty = _read_stack_quantity(cell)
            grid_slots[(row, col)] = qty
    total = sum(grid_slots.values())

    peak_mode = os.environ.get("EXODIA_INV_PEAK_FALLBACK", "auto").strip().lower()
    if peak_mode in ("1", "true", "yes", "always"):
        return _count_inventory_via_panel_peaks(panel, template_gray, thr)
    if peak_mode == "never":
        return total
    peak_total = _count_inventory_via_panel_peaks(panel, template_gray, thr)
    return max(total, peak_total)


def count_sacred_eels(
    eyes: "Eyes.BotEyes",
    *,
    threshold: Optional[float] = None,
    refresh_inventory: bool = False,
) -> int:
    """Question: How many sacred eels via legacy template match (diagnose only)?

    Deprecated for production — use ``read_inventory_labels`` +
    ``count_labeled_item_slots`` from ``bot_inventory_items`` instead.
    """
    warnings.warn(
        "count_sacred_eels is deprecated; use "
        "count_labeled_item_slots(read_inventory_labels(eyes), occ, item_name) "
        "from bot_inventory_items",
        DeprecationWarning,
        stacklevel=2,
    )
    icon = os.environ.get("EXODIA_EEL_INV_TEMPLATE", "osrs_sacredEel.png")
    return count_inventory_objects(
        eyes,
        icon,
        threshold=threshold,
        refresh_inventory=refresh_inventory,
    )
