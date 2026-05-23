"""
Automatic OSRS inventory panel detection (4×7 grid, client-local coords).

No manual ``EXODIA_INV_PANEL_RECT`` required unless you want to override.

Primary path: masked template match on the **dark inventory frame outline** from
``captures/osrs_inventory_base.png`` (override with ``EXODIA_INV_OUTLINE_TEMPLATE``).
Interior slots are ignored so item icons do not break localization.

Fallback: grid-structure scoring in the bottom-right; optional ``ui_icons.png`` hint.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_eyes import (
    INV_COLS,
    INV_ROWS,
    _clamp_roi,
    _inventory_search_roi,
    _load_template_gray,
    _match_template_peaks,
    _parse_rect_env,
    analyze_inventory_panel_occupancy,
)

_EXODIA_DIR = Path(__file__).resolve().parent
_DEFAULT_OUTLINE_TEMPLATE = _EXODIA_DIR / "captures" / "osrs_inventory_base.png"

_outline_cache: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def inventory_panel_size() -> Tuple[int, int]:
    trim_r = _env_int("EXODIA_INV_PANEL_TRIM_RIGHT", 0)
    if not os.environ.get("EXODIA_INV_PANEL_WIDTH", "").strip():
        assets = _load_inventory_outline_assets()
        if assets is not None:
            th, tw = assets[0].shape[:2]
            return max(120, tw - trim_r), th
    base_w = _env_int("EXODIA_INV_PANEL_WIDTH", 186)
    h = _env_int("EXODIA_INV_PANEL_HEIGHT", 255)
    return max(120, base_w - trim_r), h


def inventory_outline_template_path() -> Path:
    raw = os.environ.get("EXODIA_INV_OUTLINE_TEMPLATE", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_EXODIA_DIR / p).resolve()
    return _DEFAULT_OUTLINE_TEMPLATE.resolve()


def build_inventory_outline_mask(
    template_bgr: np.ndarray,
    *,
    band_frac: Optional[float] = None,
    dark_threshold: Optional[int] = None,
) -> np.ndarray:
    """
    Mask for ``matchTemplate(..., mask=...)``: dark frame band + Canny edges on the border ring.

    Ignores the slot interior so filled inventories still match the empty reference outline.
    """
    gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    frac = band_frac if band_frac is not None else _env_float("EXODIA_INV_OUTLINE_BAND", 0.12)
    band = max(6, int(min(w, h) * frac))
    ring = np.zeros((h, w), np.uint8)
    ring[:band, :] = 255
    ring[-band:, :] = 255
    ring[:, :band] = 255
    ring[:, -band:] = 255
    thr = int(dark_threshold if dark_threshold is not None else _env_int("EXODIA_INV_OUTLINE_DARK", 100))
    dark = (gray < thr).astype(np.uint8) * 255
    edges = cv2.Canny(gray, 30, 100)
    outline = cv2.bitwise_or(cv2.bitwise_and(dark, ring), cv2.bitwise_and(edges, ring))
    if int(outline.sum()) < 256:
        outline = ring
    return outline


def _load_inventory_outline_assets() -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    global _outline_cache
    if _outline_cache is not None:
        return _outline_cache
    path = inventory_outline_template_path()
    template = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if template is None or template.size == 0:
        return None
    gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    mask = build_inventory_outline_mask(template)
    _outline_cache = (template, gray, mask)
    return _outline_cache


def _pick_outline_peak(
    peaks: Sequence[Tuple[int, int, float]],
    *,
    client_bgr: np.ndarray,
    template_w: int,
    template_h: int,
    roi_x: int,
    roi_y: int,
) -> Optional[Tuple[int, int, float]]:
    """Pick the best inventory match by template score, grid validation as tie-breaker."""
    if not peaks:
        return None
    best_score = max(p[2] for p in peaks)
    margin = _env_float("EXODIA_INV_OUTLINE_SCORE_MARGIN", 0.04)
    cands = [p for p in peaks if p[2] >= best_score - margin]
    if not cands:
        cands = list(peaks)

    def _rank(p: Tuple[int, int, float]) -> Tuple[float, float]:
        rect = [roi_x + p[0], roi_y + p[1], template_w, template_h]
        grid = validate_inventory_rect(client_bgr, rect)
        return (p[2], grid)

    cands.sort(key=_rank, reverse=True)
    return cands[0]


def match_inventory_by_outline(
    client_bgr: np.ndarray,
    search_roi: Optional[List[int]] = None,
    *,
    threshold: Optional[float] = None,
) -> Optional[Tuple[List[int], float]]:
    """
    Locate inventory via dark-outline template match.

    Returns ``([x, y, w, h], score)`` for the full inventory panel in client-local
    coords. The invisible 4×7 slot grid spans this entire rectangle.
    """
    assets = _load_inventory_outline_assets()
    if assets is None or client_bgr is None or client_bgr.size == 0:
        return None

    template, gray_tpl, mask = assets
    th, tw = gray_tpl.shape[:2]
    h0, w0 = client_bgr.shape[:2]
    if search_roi is None:
        search_roi = _inventory_search_roi(w0, h0)
    sx, sy, sw, sh = _clamp_roi(w0, h0, search_roi)
    gray = cv2.cvtColor(client_bgr[sy : sy + sh, sx : sx + sw], cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < th or gray.shape[1] < tw:
        return None

    thr = threshold if threshold is not None else _env_float("EXODIA_INV_OUTLINE_THR", 0.55)
    res = cv2.matchTemplate(gray, gray_tpl, cv2.TM_CCORR_NORMED, mask=mask)
    peaks = _match_template_peaks(res, tw, th, thr, max_peaks=8)
    peak = _pick_outline_peak(
        peaks,
        client_bgr=client_bgr,
        template_w=tw,
        template_h=th,
        roi_x=sx,
        roi_y=sy,
    )
    if peak is None:
        return None
    px, py, score = peak
    panel_rect = [sx + px, sy + py, tw, th]
    return panel_rect, float(score)


def inventory_panel_corners(inventory_rect: Sequence[int]) -> Tuple[
    Tuple[int, int], Tuple[int, int], Tuple[int, int], Tuple[int, int]
]:
    """Return TL, TR, BR, BL pixel corners for ``[x, y, w, h]``."""
    fx, fy, fw, fh = (int(v) for v in inventory_rect[:4])
    tl = (fx, fy)
    tr = (fx + fw, fy)
    br = (fx + fw, fy + fh)
    bl = (fx, fy + fh)
    return tl, tr, br, bl


def inventory_grid_divider_lines(
    inventory_rect: Sequence[int],
) -> Tuple[List[int], List[int]]:
    """
    Grid line positions for the 4×7 layout inside ``inventory_rect``.

    Lines mark tile edges (gaps sit between consecutive lines).
    """
    from bot_eyes import inventory_grid_layout

    fx, fy, _fw, _fh = (int(v) for v in inventory_rect[:4])
    dx, dy, tile_w, tile_h, gap_x, gap_y, gw, gh = inventory_grid_layout(inventory_rect)
    gx0, gy0 = fx + dx, fy + dy
    xs = [gx0 + col * (tile_w + gap_x) for col in range(INV_COLS + 1)]
    ys = [gy0 + row * (tile_h + gap_y) for row in range(INV_ROWS + 1)]
    xs[-1] = gx0 + gw
    ys[-1] = gy0 + gh
    return xs, ys


def inventory_occupancy_from_client(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
) -> Tuple[Optional[List[List[bool]]], int, Optional[List[float]]]:
    """
    Classify 28 inventory slots on a client frame crop.

    Returns ``(occupancy_7x4, occupied_count, empty_prototype_bgr)``.
    Empty slots match the brown plate (low variance + color near calibrated background).
    """
    from bot_eyes import analyze_inventory_panel_occupancy

    if client_bgr is None or client_bgr.size == 0 or len(inventory_rect) != 4:
        return None, 0, None
    h0, w0 = client_bgr.shape[:2]
    ix, iy, iw, ih = (int(v) for v in inventory_rect[:4])
    sx, sy, sw, sh = _clamp_roi(w0, h0, [ix, iy, iw, ih])
    if sw <= 0 or sh <= 0:
        return None, 0, None
    panel = client_bgr[sy : sy + sh, sx : sx + sw]
    occ, _std_grid, proto = analyze_inventory_panel_occupancy(panel)
    if occ is None:
        return None, 0, proto
    count = sum(1 for row in occ for cell in row if cell)
    return occ, count, proto


def draw_inventory_occupancy_overlay(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    occupancy: Optional[List[List[bool]]] = None,
    *,
    draw_panel_outline: bool = True,
    empty_color_bgr: Tuple[int, int, int] = (0, 180, 255),
    occupied_color_bgr: Tuple[int, int, int] = (0, 120, 255),
    alpha: Optional[float] = None,
) -> np.ndarray:
    """Translucent tiles: cyan-ish = empty, orange = occupied."""
    from bot_eyes import inventory_grid_cell_xywh

    vis = client_bgr.copy()
    if draw_panel_outline:
        vis = draw_inventory_outline_overlay(vis, inventory_rect, draw_grid=False)

    if occupancy is None:
        occupancy, _, _ = inventory_occupancy_from_client(client_bgr, inventory_rect)
    if occupancy is None:
        return vis

    fill_alpha = alpha if alpha is not None else _env_float("EXODIA_INV_GRID_ALPHA", 0.35)
    fill_alpha = max(0.05, min(0.85, float(fill_alpha)))
    rect_tuple = tuple(int(v) for v in inventory_rect[:4])
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            cell = inventory_grid_cell_xywh(rect_tuple, row, col, 0)
            if cell is None:
                continue
            x, y, cw, ch = cell
            x2, y2 = x + cw, y + ch
            tint = np.array(
                occupied_color_bgr if occupancy[row][col] else empty_color_bgr,
                dtype=np.float32,
            )
            roi = vis[y:y2, x:x2].astype(np.float32)
            vis[y:y2, x:x2] = np.clip(
                roi * (1.0 - fill_alpha) + tint * fill_alpha, 0, 255
            ).astype(np.uint8)
            border = occupied_color_bgr if occupancy[row][col] else empty_color_bgr
            cv2.rectangle(vis, (x, y), (x2, y2), border, 1)
    return vis


def draw_inventory_outline_overlay(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    *,
    color_bgr: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 2,
    draw_grid: bool = True,
    grid_color_bgr: Tuple[int, int, int] = (0, 180, 255),
    grid_alpha: Optional[float] = None,
    corner_radius: int = 4,
) -> np.ndarray:
    """Return a copy of ``client_bgr`` with the inventory outline and optional 4×7 grid."""
    from bot_eyes import inventory_grid_cell_xywh

    vis = client_bgr.copy()
    tl, tr, br, bl = inventory_panel_corners(inventory_rect)
    corners = (tl, tr, br, bl)
    cv2.rectangle(vis, tl, br, color_bgr, thickness)
    for cx, cy in corners:
        cv2.circle(vis, (cx, cy), corner_radius, color_bgr, thickness)

    if draw_grid:
        alpha = grid_alpha if grid_alpha is not None else _env_float("EXODIA_INV_GRID_ALPHA", 0.35)
        alpha = max(0.05, min(0.85, float(alpha)))
        tint = np.array(grid_color_bgr, dtype=np.float32)
        rect_tuple = tuple(int(v) for v in inventory_rect[:4])
        for row in range(INV_ROWS):
            for col in range(INV_COLS):
                cell = inventory_grid_cell_xywh(rect_tuple, row, col, 0)
                if cell is None:
                    continue
                x, y, cw, ch = cell
                x2, y2 = x + cw, y + ch
                roi = vis[y:y2, x:x2].astype(np.float32)
                vis[y:y2, x:x2] = np.clip(roi * (1.0 - alpha) + tint * alpha, 0, 255).astype(
                    np.uint8
                )
                cv2.rectangle(vis, (x, y), (x2, y2), grid_color_bgr, 1)
    return vis


def panel_width_candidates() -> List[int]:
    w, _ = inventory_panel_size()
    extra = os.environ.get("EXODIA_INV_CALIB_WIDTHS", "").strip()
    if extra:
        out = sorted({max(120, int(x.strip())) for x in extra.split(",") if x.strip()})
        return out or [w]
    return sorted({max(120, w - 24), w, min(220, w + 24)})


def _sidebar_penalty(panel_bgr: np.ndarray) -> float:
    """Penalize crops that include the RuneLite tab column to the right of the slot grid."""
    if panel_bgr is None or panel_bgr.size == 0:
        return 0.0
    h0, w0 = panel_bgr.shape[:2]
    if w0 < 80:
        return 0.0
    split = max(int(w0 * 0.78), w0 - 55)
    grid = panel_bgr[:, :split]
    strip = panel_bgr[:, split:]
    if strip.size == 0 or grid.size == 0:
        return 0.0
    g = cv2.cvtColor(grid, cv2.COLOR_BGR2GRAY)
    s = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    g_std = float(np.std(g))
    s_std = float(np.std(s))
    if strip.shape[1] >= 20 and s_std > g_std * 1.6:
        return 18.0
    return 0.0


def score_inventory_grid_panel(panel_bgr: np.ndarray) -> float:
    """
    Score how well ``panel_bgr`` looks like a 4×7 inventory (no item templates required).
    """
    occ, std_grid, _ = analyze_inventory_panel_occupancy(panel_bgr)
    if occ is None or std_grid is None:
        return 0.0
    h0, w0 = panel_bgr.shape[:2]
    slot_w = w0 / float(INV_COLS)
    slot_h = h0 / float(INV_ROWS)
    if slot_w < 10 or slot_h < 10:
        return 0.0

    aspect = slot_w / max(slot_h, 1.0)
    aspect_score = max(0.0, 12.0 - abs(aspect - 1.12) * 18.0)

    confident = 0
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            s = std_grid[row][col]
            if s < 22.0 or s > 32.0:
                confident += 1

    filled = sum(1 for row in occ for cell in row if cell)
    empty = INV_ROWS * INV_COLS - filled
    balance = min(filled, empty, 14)

    score = confident * 2.5 + aspect_score + balance - _sidebar_penalty(panel_bgr)

    if os.environ.get("EXODIA_INV_CALIB_USE_EEL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        score += _eel_peak_bonus(panel_bgr) * 2.0
    return score


def _eel_peak_bonus(panel_bgr: np.ndarray) -> float:
    try:
        from bot_inventory_count import _match_inv_slot_peaks
    except ImportError:
        return 0.0
    tpl = _load_template_gray(os.path.join("images", "osrs_sacredEel.png"))
    if tpl is None:
        return 0.0
    gray = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2GRAY)
    th, tw = tpl.shape[:2]
    if gray.shape[0] < th or gray.shape[1] < tw:
        return 0.0
    res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
    thr = _env_float("EXODIA_INV_CALIB_EEL_THR", 0.55)
    return float(len(_match_inv_slot_peaks(res, tw, th, thr, max_peaks=40)))


def validate_inventory_rect(
    client_bgr: np.ndarray, rect_xywh: Sequence[int]
) -> float:
    """Quick score for an existing rect (fast path on each ``update()``)."""
    if client_bgr is None or client_bgr.size == 0 or len(rect_xywh) != 4:
        return 0.0
    h0, w0 = client_bgr.shape[:2]
    sx, sy, sw, sh = _clamp_roi(w0, h0, [int(v) for v in rect_xywh])
    if sw <= 0 or sh <= 0:
        return 0.0
    panel = client_bgr[sy : sy + sh, sx : sx + sw]
    return score_inventory_grid_panel(panel)


def refine_inventory_rect(
    client_bgr: np.ndarray,
    rect_xywh: Sequence[int],
    *,
    span_px: Optional[int] = None,
    step_px: Optional[int] = None,
) -> List[int]:
    """Nudge ``[x,y,w,h]`` to maximize grid score."""
    ix, iy, iw, ih = (int(v) for v in rect_xywh[:4])
    span = span_px if span_px is not None else _env_int("EXODIA_INV_REFINE_SPAN", 14)
    step = step_px if step_px is not None else _env_int("EXODIA_INV_REFINE_STEP", 2)
    best = [ix, iy, iw, ih]
    best_score = validate_inventory_rect(client_bgr, best)
    for dx in range(-span, span + 1, step):
        for dy in range(-span, span + 1, step):
            cand = [ix + dx, iy + dy, iw, ih]
            sc = validate_inventory_rect(client_bgr, cand)
            if sc > best_score:
                best_score = sc
                best = cand
    return best


def trim_sidebar_from_rect(
    client_bgr: np.ndarray, rect_xywh: Sequence[int]
) -> List[int]:
    """Shrink width while the right edge looks like tab icons, not item slots."""
    ix, iy, iw, ih = (int(v) for v in rect_xywh[:4])
    best = [ix, iy, iw, ih]
    best_score = validate_inventory_rect(client_bgr, best)
    for trim in range(4, 56, 4):
        cand = [ix, iy, max(120, iw - trim), ih]
        sc = validate_inventory_rect(client_bgr, cand)
        if sc >= best_score - 1.0:
            best_score = sc
            best = cand
        elif sc < best_score - 4.0:
            break
    return best


def _search_inventory_candidates(
    client_bgr: np.ndarray,
    *,
    center_xy: Optional[Tuple[int, int]] = None,
    local_span: Optional[int] = None,
    search_roi: Optional[List[int]] = None,
) -> Optional[List[int]]:
    h0, w0 = client_bgr.shape[:2]
    _, ih = inventory_panel_size()
    best_rect: Optional[List[int]] = None
    best_score = -1.0
    br_only = os.environ.get("EXODIA_INV_BR_ONLY", "").strip().lower() in ("1", "true", "yes")
    roi_x, roi_y, roi_w, roi_h = 0, 0, w0, h0
    if search_roi is not None and len(search_roi) == 4:
        roi_x, roi_y, roi_w, roi_h = _clamp_roi(w0, h0, search_roi)

    for iw in panel_width_candidates():
        use_local = center_xy is not None
        if use_local:
            cx, cy = center_xy
            span = local_span if local_span is not None else _env_int("EXODIA_INV_LOCAL_SPAN", 80)
            x_step = _env_int("EXODIA_INV_LOCAL_X_STEP", 6)
            y_step = _env_int("EXODIA_INV_LOCAL_Y_STEP", 6)
            tlx = cx - iw // 2
            tly = cy - ih // 2
            ix_lo = max(roi_x, tlx - span)
            ix_hi = min(roi_x + roi_w - iw, tlx + span)
            iy_lo = max(roi_y, tly - span)
            iy_hi = min(roi_y + roi_h - ih, tly + span)
            positions = (
                (ix, iy)
                for ix in range(ix_lo, ix_hi + 1, x_step)
                for iy in range(iy_lo, iy_hi + 1, y_step)
            )
        else:
            x_step = _env_int("EXODIA_INV_CALIB_X_STEP", 20)
            y_step = _env_int("EXODIA_INV_CALIB_Y_STEP", 20)
            positions = (
                (ix, iy)
                for iy in range(roi_y, max(roi_y + 1, roi_y + roi_h - ih), y_step)
                for ix in range(roi_x, max(roi_x + 1, roi_x + roi_w - iw), x_step)
            )

        for ix, iy in positions:
            if br_only and (ix < int(w0 * 0.45) or iy < int(h0 * 0.45)):
                continue
            panel = client_bgr[iy : iy + ih, ix : ix + iw]
            if panel.size == 0:
                continue
            sc = score_inventory_grid_panel(panel)
            if sc > best_score:
                best_score = sc
                best_rect = [ix, iy, iw, ih]

    min_score = _env_float("EXODIA_INV_MIN_GRID_SCORE", 12.0)
    if best_rect is None or best_score < min_score:
        return None
    return best_rect


def template_anchor_center(
    client_bgr: np.ndarray,
    search_roi: Optional[List[int]] = None,
    *,
    threshold: float = 0.38,
) -> Optional[Tuple[int, int]]:
    """Optional hint from ``ui_icons.png`` / ``Session_Inventory.png`` (top-left of match)."""
    gray = cv2.cvtColor(client_bgr, cv2.COLOR_BGR2GRAY)
    h0, w0 = gray.shape[:2]
    off_x, off_y = 0, 0
    if search_roi is None:
        search_roi = _inventory_search_roi(w0, h0)
    if search_roi is not None and len(search_roi) == 4:
        sx, sy, sw, sh = _clamp_roi(w0, h0, search_roi)
        gray = gray[sy : sy + sh, sx : sx + sw]
        off_x, off_y = sx, sy

    best: Optional[Tuple[int, int, float]] = None
    for filename in ("ui_icons.png", "Session_Inventory.png"):
        template = _load_template_gray(os.path.join("images", filename))
        if template is None:
            continue
        tw, th = template.shape[::-1]
        if gray.shape[0] < th or gray.shape[1] < tw:
            continue
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        peaks = _match_template_peaks(res, tw, th, threshold, max_peaks=4)
        if not peaks:
            continue
        peaks.sort(key=lambda t: -t[2])
        px, py, sc = peaks[0]
        cx = off_x + px + tw // 2
        cy = off_y + py + th // 2
        if best is None or sc > best[2]:
            best = (cx, cy, sc)
    if best is None:
        return None
    inv_off_x = _env_int("EXODIA_INV_OFFSET_X", 20)
    inv_off_y = _env_int("EXODIA_INV_OFFSET_Y", 35)
    iw, ih = inventory_panel_size()
    return best[0] + inv_off_x + iw // 2, best[1] + inv_off_y + ih // 2


def auto_detect_inventory_rect(
    client_bgr: np.ndarray,
    *,
    last_rect: Optional[Sequence[int]] = None,
    search_roi: Optional[List[int]] = None,
) -> Optional[List[int]]:
    """
    Detect ``[x, y, width, height]`` of the 4×7 inventory grid in **client-local** coords.
    """
    _ = last_rect
    manual = _parse_rect_env("EXODIA_INV_PANEL_RECT")
    if manual:
        return manual
    if client_bgr is None or client_bgr.size == 0:
        return None

    if search_roi is None:
        h0, w0 = client_bgr.shape[:2]
        search_roi = _inventory_search_roi(w0, h0)

    use_outline = os.environ.get("EXODIA_INV_OUTLINE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    if use_outline:
        matched = match_inventory_by_outline(client_bgr, search_roi)
        if matched is not None:
            rect, score = matched
            min_score = _env_float("EXODIA_INV_OUTLINE_MIN_SCORE", 0.55)
            min_grid = _env_float("EXODIA_INV_MIN_GRID_SCORE", 12.0)
            if score >= min_score and validate_inventory_rect(client_bgr, rect) >= min_grid:
                rect = refine_inventory_rect(client_bgr, rect)
                return rect

    center = None
    local_span = None
    hint = template_anchor_center(client_bgr, search_roi)
    if hint is not None:
        center = hint
        local_span = _env_int("EXODIA_INV_HINT_SPAN", 90)

    rect = _search_inventory_candidates(
        client_bgr, center_xy=center, local_span=local_span, search_roi=search_roi
    )
    if rect is None and center is not None:
        rect = _search_inventory_candidates(client_bgr, search_roi=search_roi)
    if rect is None:
        return None

    rect = refine_inventory_rect(client_bgr, rect)
    rect = trim_sidebar_from_rect(client_bgr, rect)
    return rect


def calibrate_inventory_rect_from_client(
    client_bgr: np.ndarray,
    *,
    min_filled_slots: int = 1,
) -> Optional[List[int]]:
    """Back-compat wrapper — ``min_filled_slots`` ignored; uses grid score instead."""
    _ = min_filled_slots
    return auto_detect_inventory_rect(client_bgr)
