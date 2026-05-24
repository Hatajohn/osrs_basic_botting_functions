#imports
from __future__ import annotations

import copy
import math
import os
import random
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import pytesseract
from sklearn.cluster import DBSCAN

import bot_env as Env

_DEFAULT_COLOR_BOUNDARIES = [([180, 0, 180], [220, 20, 220])]

# Legacy default (top-left). Prefer ``resolve_action_strip_roi_client`` from inventory layout.
_ACTION_STRIP_RECT_CLIENT = [25, 50, 100, 30]
ACTION_STRIP_ROI_CLIENT_LOCAL = _ACTION_STRIP_RECT_CLIENT  #: fallback alias for tooling


def _env_bool_action(key: str, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _parse_rect_env(key: str) -> Optional[List[int]]:
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return None
    parts = [int(x.strip()) for x in raw.replace(" ", "").split(",")]
    if len(parts) == 4:
        return parts
    return None


def resolve_action_strip_roi_client(
    *,
    inventory_rect: Optional[Sequence[int]] = None,
    frame_w: int = 0,
    frame_h: int = 0,
) -> List[int]:
    """
    OSRS skilling action text sits **left of the inventory** (bottom-right UI).

    Priority: ``EXODIA_ACTION_STRIP_RECT`` > left-of-``inventory_rect`` > legacy top-left.
    """
    manual = _parse_rect_env("EXODIA_ACTION_STRIP_RECT")
    if manual:
        return manual

    if (
        _env_bool_action("EXODIA_ACTION_STRIP_LEFT_OF_INV", True)
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
    """Client-local ROI covering inventory + action line (bottom-right UI)."""
    raw = _parse_rect_env("EXODIA_ACTION_STRIP_SEARCH_ROI")
    if raw:
        return raw
    return [
        max(0, int(frame_w * 0.50)),
        max(0, int(frame_h * 0.52)),
        max(200, int(frame_w * 0.50)),
        max(180, int(frame_h * 0.48)),
    ]


def _inventory_search_roi(frame_w: int, frame_h: int) -> List[int]:
    raw = _parse_rect_env("EXODIA_INV_SEARCH_ROI")
    if raw:
        return raw
    # Default OSRS layout: inventory anchored bottom-right. Set EXODIA_INV_SEARCH_FULL=1 to search everywhere.
    if os.environ.get("EXODIA_INV_SEARCH_FULL", "").strip().lower() in ("1", "true", "yes"):
        return [0, 0, int(frame_w), int(frame_h)]
    return _bottom_right_ui_search_roi(frame_w, frame_h)


def _mask_ui_panels_after_update() -> bool:
    """
    When True (default), ``update()`` draws black bars over detected inventory / chat regions on
    ``curr_client`` for legacy world-facing vision paths.

    Set ``EXODIA_MASK_PANELS=0`` to skip that — rely on ``inventory_rect``, ``chat_rect``, and
    ``crop_client_local()`` instead (single consistent frame via ``curr_client_unmasked`` / crop).
    """
    v = (os.environ.get("EXODIA_MASK_PANELS") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _match_template_peaks(
    res: np.ndarray,
    template_w: int,
    template_h: int,
    threshold: float,
    max_peaks: int = 32,
) -> List[Tuple[int, int, float]]:
    """
    Non-maximum suppression on ``TM_CCOEFF_NORMED`` map: repeated ``minMaxLoc`` with suppression windows.
    Returns ``(x, y, score)`` in **result map** coordinates (top-left of template match).
    """
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


@dataclass
class TemplateMatch:
    """One template peak: centers in screen space and source-image space."""

    screen_xy: List[int]
    client_xy: List[int]
    score: float


@dataclass
class LocateImageResult:
    """Structured ``locate_image`` output for agents and ``Observation.meta``."""

    template_filename: str
    found: bool
    error: Optional[str]
    matches: List[TemplateMatch]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_filename": self.template_filename,
            "found": self.found,
            "error": self.error,
            "matches": [
                {"screen_xy": m.screen_xy, "client_xy": m.client_xy, "score": m.score} for m in self.matches
            ],
        }


def _clamp_roi(width, height, roi):
    """Clamp ``roi`` ``[sx, sy, sw, sh]`` to image bounds; returns ``(sx, sy, sw, sh)``."""
    sx, sy, sw, sh = (int(roi[i]) for i in range(4))
    sx = max(0, min(sx, width - 1))
    sy = max(0, min(sy, height - 1))
    sw = max(1, min(sw, width - sx))
    sh = max(1, min(sh, height - sy))
    return sx, sy, sw, sh


INV_COLS = 4
INV_ROWS = 7
INV_SLOTS = INV_COLS * INV_ROWS


def _env_positive_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw, 10)
        return max(0, v)
    except ValueError:
        return default


def _env_positive_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        return max(0.0, v)
    except ValueError:
        return default


def _parse_csv_bgr_tag(key: str) -> Optional[Tuple[float, float, float]]:
    """Parse ``EXODIA_*`` value ``'B,G,R'`` as floats."""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3:
        return None
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None


def _parse_pair_env(key: str, default: Tuple[int, int]) -> Tuple[int, int]:
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return default
    parts = [p.strip() for p in raw.replace(" ", "").split(",")]
    if len(parts) != 2:
        return default
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return default


def inventory_grid_layout(
    inventory_xywh: Sequence[int],
) -> Tuple[int, int, int, int, int, int, int, int]:
    """
    Grid geometry inside panel ``[ix, iy, iw, ih]``.

    Returns ``(dx, dy, tile_w, tile_h, gap_x, gap_y, field_w, field_h)``.
    Defaults (reference panel 283×382): offset 30×20, tile 50×45, gaps 7×5.
    """
    if len(inventory_xywh) != 4:
        return 0, 0, 0, 0, 0, 0, 0, 0
    _, _, iw, ih = (int(x) for x in inventory_xywh[:4])
    ref_w = _env_positive_int("EXODIA_INV_GRID_REF_W", 283)
    ref_h = _env_positive_int("EXODIA_INV_GRID_REF_H", 382)

    manual_inset = _parse_rect_env("EXODIA_INV_GRID_INSET")
    if manual_inset:
        dx, dy, gw, gh = (int(manual_inset[i]) for i in range(4))
        tile_w = max(1, gw // INV_COLS)
        tile_h = max(1, gh // INV_ROWS)
        gap_x = max(0, (gw - INV_COLS * tile_w) // max(1, INV_COLS - 1))
        gap_y = max(0, (gh - INV_ROWS * tile_h) // max(1, INV_ROWS - 1))
    else:
        dx, dy = _parse_pair_env("EXODIA_INV_GRID_OFFSET", (30, 20))
        tile_w, tile_h = _parse_pair_env("EXODIA_INV_TILE", (50, 45))
        gap_x, gap_y = _parse_pair_env("EXODIA_INV_TILE_GAP", (7, 5))
        gw = INV_COLS * tile_w + (INV_COLS - 1) * gap_x
        gh = INV_ROWS * tile_h + (INV_ROWS - 1) * gap_y

    if iw <= 0 or ih <= 0:
        return 0, 0, 0, 0, 0, 0, 0, 0
    if ref_w > 0 and ref_h > 0 and (iw, ih) != (ref_w, ref_h):
        sx = iw / float(ref_w)
        sy = ih / float(ref_h)
        dx = int(round(dx * sx))
        dy = int(round(dy * sy))
        tile_w = max(1, int(round(tile_w * sx)))
        tile_h = max(1, int(round(tile_h * sy)))
        gap_x = max(0, int(round(gap_x * sx)))
        gap_y = max(0, int(round(gap_y * sy)))
        gw = INV_COLS * tile_w + (INV_COLS - 1) * gap_x
        gh = INV_ROWS * tile_h + (INV_ROWS - 1) * gap_y

    return dx, dy, tile_w, tile_h, gap_x, gap_y, gw, gh


def inventory_grid_field_xywh(
    inventory_xywh: Sequence[int],
) -> Tuple[int, int, int, int]:
    """
    Slot field ``(dx, dy, gw, gh)`` inside panel ``[ix, iy, iw, ih]``.

    The 4×7 tiles sit inset within the decorative frame; see ``inventory_grid_layout``.
    """
    dx, dy, _, _, _, _, gw, gh = inventory_grid_layout(inventory_xywh)
    return dx, dy, gw, gh


def inventory_grid_cell_xywh(
    inventory_xywh: Tuple[int, ...], row: int, col: int, inset_px: int
) -> Optional[Tuple[int, int, int, int]]:
    """
    One slot ROI inside ``inventory_rect`` ``[ix, iy, iw, ih]``.

    ``row`` 0 = top, ``col`` 0 = left; row-major order matches slot index ``row*4+col``.
    """
    if len(inventory_xywh) != 4:
        return None
    ix, iy, iw, ih = (int(x) for x in inventory_xywh[:4])
    if iw < INV_COLS or ih < INV_ROWS:
        return None
    dx, dy, tile_w, tile_h, gap_x, gap_y, _, _ = inventory_grid_layout(inventory_xywh)
    if tile_w < 2 or tile_h < 2:
        return None
    inset = max(0, int(inset_px))
    if tile_w <= 2 * inset or tile_h <= 2 * inset:
        inset = 0
    x0 = ix + dx + col * (tile_w + gap_x) + inset
    y0 = iy + dy + row * (tile_h + gap_y) + inset
    w_c = tile_w - 2 * inset
    h_c = tile_h - 2 * inset
    if w_c < 2 or h_c < 2:
        return None
    return x0, y0, w_c, h_c


def inventory_slot_screen_xy(
    inventory_xywh: Sequence[int],
    client_rect: Sequence[int],
    row: int,
    col: int,
    *,
    inset_px: Optional[int] = None,
) -> Optional[Tuple[int, int]]:
    """Center of slot ``(row, col)`` in Win32 screen coordinates."""
    if len(client_rect) < 4:
        return None
    inset = inventory_cell_inset_px(inventory_xywh) if inset_px is None else max(0, int(inset_px))
    cell = inventory_grid_cell_xywh(tuple(inventory_xywh), row, col, inset)
    if cell is None:
        return None
    x, y, w, h = cell
    return int(client_rect[0]) + x + w // 2, int(client_rect[1]) + y + h // 2


def inventory_cell_inset_px(inventory_xywh: Sequence[int]) -> int:
    """Sample inset inside each tile — auto from tile size unless ``EXODIA_INV_CELL_INSET`` set."""
    raw = os.environ.get("EXODIA_INV_CELL_INSET", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    _, _, tile_w, tile_h, _, _, _, _ = inventory_grid_layout(inventory_xywh)
    return max(3, min(tile_w, tile_h) // 7)


def _cell_laplacian_variance(cell_bgr: np.ndarray) -> float:
    """Variance of Laplacian — high when slot has icon edges despite brown-plate color match."""
    if cell_bgr is None or cell_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.var(cv2.Laplacian(gray, cv2.CV_64F)))


def analyze_inventory_panel_occupancy(
    inventory_panel_bgr: np.ndarray,
) -> Tuple[
    Optional[List[List[bool]]], Optional[List[List[float]]], Optional[List[float]]
]:
    """
    Classify 28 slots: **True** = occupied, **False** = empty (uniform brown plate).

    Slots that pass the std/color empty test but exceed
    ``EXODIA_INV_LAPLACE_MIN_VAR`` edge variance are treated as occupied
    (catches low-contrast icons that blend with the slot background).

    Returns ``(occupancy_7x4, grayscale_std_7x4_or_None, prototype_bgr_or_None)``.
    """
    if inventory_panel_bgr is None or inventory_panel_bgr.size == 0:
        return None, None, None
    h0, w0 = inventory_panel_bgr.shape[:2]
    if h0 < INV_ROWS * 4 or w0 < INV_COLS * 4:
        return None, None, None

    pseudo_rect = [0, 0, w0, h0]
    inset_px = inventory_cell_inset_px(pseudo_rect)
    std_thresh = _env_positive_float("EXODIA_INV_CELL_STD_THRESHOLD", 22.0)
    color_delta_cap = _env_positive_float("EXODIA_INV_EMPTY_BGR_MAX_DELTA", 12.0)
    cal_k = max(4, min(INV_SLOTS, _env_positive_int("EXODIA_INV_EMPTY_CALIBRATION_K", 10)))

    lap_min = _env_positive_float("EXODIA_INV_LAPLACE_MIN_VAR", 300.0)
    rects: List[Optional[Tuple[int, int, int, int]]] = []
    grays_stds: List[float] = []
    mean_bgrs: List[np.ndarray] = []
    cell_crops: List[Optional[np.ndarray]] = []

    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            r = inventory_grid_cell_xywh(tuple(pseudo_rect), row, col, inset_px)
            rects.append(r)
            if r is None:
                grays_stds.append(1e9)
                mean_bgrs.append(np.zeros(3))
                cell_crops.append(None)
                continue
            sx, sy, sw, sh = r
            cell = inventory_panel_bgr[sy : sy + sh, sx : sx + sw]
            cell_crops.append(cell)
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            gray = cv2.blur(gray, (3, 3))
            grays_stds.append(float(np.std(gray)))
            mean_bgrs.append(np.mean(cell.reshape(-1, 3), axis=0))

    indexed = sorted(range(INV_SLOTS), key=lambda i: grays_stds[i])
    cal_idxs = indexed[:cal_k]
    stacked = np.array([mean_bgrs[j] for j in cal_idxs], dtype=np.float64)
    prototype = np.median(stacked, axis=0)

    fb = _parse_csv_bgr_tag("EXODIA_INV_FALLBACK_EMPTY_BGR")
    if fb is not None:
        prototype = (np.asarray(fb, dtype=np.float64) + prototype) / 2.0

    lb = _parse_csv_bgr_tag("EXODIA_INV_EMPTY_BGR_LOWER")
    ub = _parse_csv_bgr_tag("EXODIA_INV_EMPTY_BGR_UPPER")

    occ: List[List[bool]] = []
    std_grid: List[List[float]] = []
    for row in range(INV_ROWS):
        row_occ: List[bool] = []
        row_std: List[float] = []
        for col in range(INV_COLS):
            idx = row * INV_COLS + col
            std_g = grays_stds[idx]
            mu = mean_bgrs[idx].astype(np.float64)
            row_std.append(std_g)

            uniform = std_g < std_thresh
            color_delta = float(np.max(np.abs(mu - prototype)))
            color_near = color_delta <= color_delta_cap
            empty = uniform and color_near
            if lb is not None and ub is not None:
                band = np.all((mu >= np.asarray(lb)) & (mu <= np.asarray(ub)))
                empty = empty and band

            occupied = not empty
            if not occupied and lap_min > 0:
                cell = cell_crops[idx]
                if cell is not None and _cell_laplacian_variance(cell) >= lap_min:
                    occupied = True

            row_occ.append(occupied)
        occ.append(row_occ)
        std_grid.append(row_std)

    proto_list = [float(prototype[i]) for i in range(3)]
    return occ, std_grid, proto_list


def _load_template_gray(path):
    """Load a single-channel template or return ``None`` if missing or empty."""
    t = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if t is None or t.size == 0:
        return None
    return t


def _mask_and_contours_bgr(image_bgr, boundaries):
    """Apply each BGR band sequentially; return ``(thresh, contours)`` from the last band."""
    thresh = None
    contours = ()
    for lower, upper in boundaries:
        lower = np.array(lower, dtype=np.uint8)
        upper = np.array(upper, dtype=np.uint8)
        mask = cv2.inRange(image_bgr, lower, upper)
        _, thresh = cv2.threshold(mask, 40, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return thresh, contours


def resolve_tesseract_cmd(explicit=None):
    """Prefer explicit arg, then EXODIA_TESSERACT_CMD, then PATH, then 'tesseract'."""
    if explicit:
        return explicit
    env = os.environ.get("EXODIA_TESSERACT_CMD", "").strip()
    if env:
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    return "tesseract"


def run_ocr(
    roi_bgr,
    psm=None,
    whitelist=None,
    scale=None,
):
    """
    Central OCR hook: optional downscale, PSM, whitelist. Call per ROI to stay tick-budget friendly.
    ``scale``: if set (e.g. 0.5), resize ROI before OCR for speed.
    """
    img = roi_bgr
    if scale is not None and 0 < scale < 1.0:
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    parts = []
    if psm is not None:
        parts.append("--psm %d" % int(psm))
    if whitelist:
        parts.append("-c tessedit_char_whitelist=%s" % whitelist)
    config = " ".join(parts)
    return pytesseract.image_to_string(img, config=config).strip()


# This class handles object recognition and the images required for the rest of the bot to function
class BotEyes():
    def __init__(self, win_rect=[], DEBUG=False, tesseract_cmd=None):
        self.tesseract_path = resolve_tesseract_cmd(tesseract_cmd)
        pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
        _ok = os.path.isfile(self.tesseract_path) or shutil.which(self.tesseract_path) is not None
        if not _ok:
            print(
                "Warning: Tesseract may be missing (%r). Set EXODIA_TESSERACT_CMD or install tesseract-ocr."
                % (self.tesseract_path,)
            )
        # Inventory location in a client screenshot -> easier for image recognition and future screenshots
        self.inventory_rect = None
        self.action_strip_rect: Optional[List[int]] = None

        # Inventory location on monitor -> easier for click locations
        self.inventory_global = None

        # Image of current inventory -> easier for image recognition
        self.curr_inventory = None

        # Client rect -> pass from ``ClientWindow`` (``win_rect``), add a bit for the gap made by the top and right sides
        self.client_rect = win_rect
        self.chat_rect = None

        # Image of client (**after** inventory/chat masks in ``update()``).
        self.curr_client = None

        # Snapshot before masking — use for segmented exports / chat OCR.
        self.curr_client_unmasked = None

        # Center of the client
        self.local_center = None
        self.global_center = None

        # Debug flag
        self._DEBUG = DEBUG

        # Latest JSON-serializable framing snapshot (filled in ``update()``).
        self.perception_envelope: Optional[Dict[str, Any]] = None


    # Force debugging at any point
    def force_debug(self, DEBUG=False):
        self._DEBUG=DEBUG

    
    def _sync_inventory_global(self) -> None:
        """Refresh screen coords for ``inventory_rect`` after ``client_rect`` moves (no re-detect)."""
        if (
            self.inventory_rect is None
            or len(self.inventory_rect) != 4
            or self.client_rect is None
        ):
            return
        self.inventory_global = [
            self.inventory_rect[0] + self.client_rect[0],
            self.inventory_rect[1] + self.client_rect[1],
            self.inventory_rect[2],
            self.inventory_rect[3],
        ]

    # Updates the inventory image
    def check_inventory(self):
        """Crop the inventory slot grid from ``curr_client`` using ``inventory_rect`` (same frame as the client grab)."""
        if self.curr_client is None:
            self.curr_inventory = None
            return
        if self.inventory_rect is None or len(self.inventory_rect) != 4:
            self.curr_inventory = None
            return
        h0, w0 = self.curr_client.shape[:2]
        sx, sy, sw, sh = _clamp_roi(w0, h0, self.inventory_rect)
        self.curr_inventory = self.curr_client[sy : sy + sh, sx : sx + sw].copy()


    # Updates the client image from stream buffer or sync grab.
    def check_client(self):
        """Capture client rectangle into ``curr_client`` (alias for ``capture_frame``)."""
        self.capture_frame()

    def set_rect_geometry(self, new_rect):
        """Update client/chat ROIs without capturing a frame."""
        self.client_rect = new_rect
        self.chat_rect = [0, self.client_rect[3] - 30, 520, 30]

    def setRect(self, new_rect, refresh=True):
        """Set client rect; optionally refresh frame (``capture_frame``)."""
        self.set_rect_geometry(new_rect)
        if refresh:
            self.capture_frame()

    def capture_frame(self):
        """Pull latest frame (buffer copy when stream active) and derive crops/masks."""
        self.find_center()
        self.curr_client = Env.screen_image(rect=self.client_rect, DEBUG=self._DEBUG)
        if self.inventory_rect is None:
            self.find_inventory(refresh_client=False)
        else:
            self._sync_inventory_global()
        self.find_action_strip_rect(refresh_client=False)
        self.check_inventory()

        self.curr_client_unmasked = (
            None if self.curr_client is None else np.copy(np.asarray(self.curr_client, dtype=np.uint8))
        )

        if _mask_ui_panels_after_update():
            if self.inventory_rect is not None and len(self.inventory_rect) == 4:
                ix, iy, iw, ih = self.inventory_rect
                cv2.rectangle(
                    self.curr_client,
                    (ix, iy),
                    (ix + iw, iy + ih),
                    color=(0, 0, 0),
                    thickness=-1,
                )
            if self.chat_rect is not None and len(self.chat_rect) == 4:
                cx, cy, cw, ch = self.chat_rect
                cv2.rectangle(
                    self.curr_client,
                    (cx, cy),
                    (cx + cw, cy + ch),
                    color=(0, 0, 0),
                    thickness=-1,
                )

        if self._DEBUG:
            print('Chat rect vs client_rect ', self.chat_rect, self.inventory_rect, self.client_rect)
            Env.debug_view(self.curr_client, 'UPDATE CLIENT')

        self._rebuild_perception_envelope()

    def update(self):
        """One ``capture_frame()`` per tick; derive inventory crops from rects; UI blackout optional."""
        self.capture_frame()

    def _rebuild_perception_envelope(self) -> None:
        """Geometry and capture metadata only (no task semantics). JSON-serializable."""
        mask_regions: List[Dict[str, Any]] = []
        if self.inventory_rect is not None and len(self.inventory_rect) == 4:
            mask_regions.append({"name": "inventory_panel", "rect_client_local": [int(x) for x in self.inventory_rect]})
        if self.chat_rect is not None and len(self.chat_rect) == 4:
            mask_regions.append({"name": "chat_strip", "rect_client_local": [int(x) for x in self.chat_rect]})

        def _shape(im) -> Optional[List[int]]:
            if im is None:
                return None
            s = im.shape
            return [int(s[0]), int(s[1])]

        panel_for_slots = self._inventory_panel_bgr_for_slots()
        if panel_for_slots is not None:
            occ, inv_std_grid, inv_proto_bgr = analyze_inventory_panel_occupancy(panel_for_slots)
        else:
            occ, inv_std_grid, inv_proto_bgr = None, None, None
        inv_scores_debug = self._DEBUG or (
            os.environ.get("EXODIA_INV_CELL_DEBUG", "").strip().lower() in ("1", "true", "yes")
        )

        pe: Dict[str, Any] = {
            "client_rect": [int(x) for x in self.client_rect] if self.client_rect else [],
            "ui_blackout_panels_applied": _mask_ui_panels_after_update(),
            "inventory_rect_client_local": [int(x) for x in self.inventory_rect]
            if self.inventory_rect and len(self.inventory_rect) == 4
            else None,
            "inventory_global": [int(x) for x in self.inventory_global]
            if self.inventory_global and len(self.inventory_global) == 4
            else None,
            "inventory_cols_rows": [INV_COLS, INV_ROWS],
            "inventory_slot_occupancy": occ,
            "inventory_empty_prototype_bgr": inv_proto_bgr,
            "inventory_slot_items": None,
            "local_center": [int(self.local_center[0]), int(self.local_center[1])]
            if self.local_center and len(self.local_center) >= 2
            else None,
            "global_center": [int(self.global_center[0]), int(self.global_center[1])]
            if self.global_center and len(self.global_center) >= 2
            else None,
            "mask_regions_applied_to_curr_client": mask_regions,
            "curr_client_shape_hw": _shape(self.curr_client),
            "curr_client_unmasked_shape_hw": _shape(self.curr_client_unmasked),
            "curr_inventory_shape_hw": _shape(self.curr_inventory),
            "capture_backend": Env.capture_backend_label(),
            "action_strip_roi_client_local": list(
                self.action_strip_roi_client()
                if self.curr_client is not None and self.curr_client.size > 0
                else _ACTION_STRIP_RECT_CLIENT
            ),
        }
        if inv_scores_debug and inv_std_grid is not None:
            pe["inventory_cell_debug_scores"] = inv_std_grid
        self.perception_envelope = pe

    # Grab inventory screenshot region after ensuring layout is known.
    def grab_inventory(self):
        try:
            if self.inventory_rect is None:
                self.find_inventory(refresh_client=False)
            if self._DEBUG and self.inventory_global is not None:
                screenshot_check = Env.screen_image()
                ix, iy, iw, ih = self.inventory_global
                screenshot_check = cv2.rectangle(
                    screenshot_check,
                    (ix, iy),
                    (ix + iw, iy + ih),
                    color=(0, 255, 0),
                    thickness=2,
                )
                Env.debug_view(screenshot_check, title="True inventory position")
        except Exception:
            return False
        self.check_inventory()
        return True


    # Locate the inventory on the client screen and returns the corners
    def find_inventory(
        self,
        threshold=0.38,
        search_roi=None,
        *,
        refresh_client: bool = True,
        force: bool = False,
    ):
        """
        Auto-detect the 4×7 inventory grid (``bot_inventory_detect``).

        Runs full detection once at startup; later ``update()`` calls only crop the cached
        rect. Pass ``force=True`` or set ``EXODIA_INV_FORCE_RECALIB=1`` to search again.
        """
        _ = threshold
        force = force or os.environ.get("EXODIA_INV_FORCE_RECALIB", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if (
            not force
            and self.inventory_rect is not None
            and len(self.inventory_rect) == 4
        ):
            if refresh_client or self.curr_client is None:
                self.check_client()
            self._sync_inventory_global()
            self.check_inventory()
            return self.inventory_rect

        if refresh_client or self.curr_client is None:
            self.check_client()
        image = self.curr_client
        if image is None or image.size == 0:
            return []

        from bot_inventory_detect import auto_detect_inventory_rect, validate_inventory_rect

        auto_off = os.environ.get("EXODIA_INV_AUTO", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        if not auto_off:
            return []

        rect = auto_detect_inventory_rect(image, last_rect=None, search_roi=search_roi)
        if rect is None:
            self.inventory_rect = None
            self.inventory_global = None
            self.curr_inventory = None
            return []

        if os.environ.get("EXODIA_INV_DEBUG", "").strip().lower() in ("1", "true", "yes"):
            print(
                "find_inventory: auto -> %s (score %.1f)"
                % (rect, validate_inventory_rect(image, rect))
            )

        self.inventory_rect = rect
        self.inventory_global = [
            rect[0] + self.client_rect[0],
            rect[1] + self.client_rect[1],
            rect[2],
            rect[3],
        ]
        if self._DEBUG:
            vis = copy.deepcopy(image)
            ix, iy, iw, ih = rect
            cv2.rectangle(vis, (ix, iy), (ix + iw, iy + ih), (0, 0, 255), 2)
            Env.debug_view(vis, "inventory_rect")
        self.check_inventory()
        return self.inventory_rect


    # Locate the chat area on the client screen and returns the corners
    def find_chat(self, image, threshold=0.7):
        """Returns chat ROI corners in image coords, or ``None`` if template missing or no match."""
        image_gray = cv2.cvtColor(Env.resize_image(image, scale_percent=70), cv2.COLOR_BGR2GRAY)
        template = _load_template_gray("images/chat_template.png")
        if template is None:
            print("find_chat: missing or empty template images/chat_template.png")
            return None
        w, h = template.shape[::-1]
        res = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)
        peaks = _match_template_peaks(res, w, h, threshold, max_peaks=16)
        if not peaks:
            return None
        peaks.sort(key=lambda t: -t[2])
        pt = (peaks[0][0], peaks[0][1])
        cv2.rectangle(image, pt, (pt[0] + w, pt[1] + h), (0, 0, 0), 2)
        cv2.circle(image, pt, radius=10, color=(255, 0, 0), thickness=2)
        x1, y1, x2, y2 = pt[0] + 20, pt[1] + 35, pt[0] + 200, pt[1] + 290
        if self._DEBUG:
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
        return x1, y1, x2, y2


    # A function that sets the local and global centers. This can be used in other functions since the character is always semi-centered
    # Requires ``ClientWindow`` to assign win_rect in init, otherwise just finds the global center of a rectangle
    def find_center(self):
        #self.client_rect is top-left (x, y) then width and height
        image_center = [math.floor(self.client_rect[2]/2)  - 20, math.floor(self.client_rect[3]/2) + 25]
        # Adding 50 so it reflects the character's position rather than the center of the client
        true_center = [image_center[0] + self.client_rect[0], image_center[1] + self.client_rect[1]]

        self.local_center = image_center
        self.global_center = true_center

    def _client_bgr_for_text_crops(self) -> Optional[np.ndarray]:
        """Prefer ``curr_client_unmasked`` so chat/action strips are not covered by UI masks."""
        if self.curr_client_unmasked is not None:
            return self.curr_client_unmasked
        return self.curr_client

    def crop_client_local(
        self, rect_xywh: List[int], *, prefer_unmasked: bool = True
    ) -> Optional[np.ndarray]:
        """
        Crop ``rect_xywh`` (``[x, y, width, height]`` in **client-local** coordinates).

        Defaults to unmasked pixels from the last ``update()`` when present.
        """
        base = (
            self.curr_client_unmasked
            if prefer_unmasked and self.curr_client_unmasked is not None
            else self.curr_client
        )
        if base is None:
            return None
        h0, w0 = base.shape[:2]
        sx, sy, sw, sh = _clamp_roi(w0, h0, rect_xywh)
        if sw <= 0 or sh <= 0:
            return None
        return base[sy : sy + sh, sx : sx + sw].copy()

    def resolve_inventory_slot_items(self) -> Optional[List[List[Optional[str]]]]:
        """
        Per-slot item identity (name, id, hash, …). **Not implemented** — returns ``None``.
        Use with :meth:`compute_inventory_slot_occupancy` for empty vs full; wire templates/embeddings later.
        """
        return None

    def _inventory_panel_bgr_for_slots(self) -> Optional[np.ndarray]:
        """Same pixels as ``curr_inventory`` when possible; else crops unmasked client."""
        if self.curr_inventory is not None and self.curr_inventory.size:
            return np.asarray(self.curr_inventory, dtype=np.uint8)
        if self.inventory_rect is None or len(self.inventory_rect) != 4:
            return None
        base = (
            self.curr_client_unmasked
            if self.curr_client_unmasked is not None
            else self.curr_client
        )
        if base is None:
            return None
        h0, w0 = base.shape[:2]
        sx, sy, sw, sh = _clamp_roi(w0, h0, self.inventory_rect)
        return base[sy : sy + sh, sx : sx + sw].copy()

    def compute_inventory_slot_occupancy(self) -> Optional[List[List[bool]]]:
        """``True`` = occupied, ``False`` = empty; ``None`` if no inventory panel image."""
        panel = self._inventory_panel_bgr_for_slots()
        occ, _, _ = analyze_inventory_panel_occupancy(panel)
        return occ

    def draw_inventory_grid_debug(self) -> Optional[np.ndarray]:
        """BGR copy of client with inventory outline and per-slot filled/empty tint."""
        base = self.curr_client_unmasked if self.curr_client_unmasked is not None else self.curr_client
        if base is None or self.inventory_rect is None or len(self.inventory_rect) != 4:
            return None
        vis = base.copy()
        occ = self.compute_inventory_slot_occupancy()
        ix, iy, iw, ih = [int(v) for v in self.inventory_rect[:4]]
        h0, w0 = vis.shape[:2]
        ix, iy, iw, ih = _clamp_roi(w0, h0, [ix, iy, iw, ih])
        cv2.rectangle(vis, (ix, iy), (ix + iw, iy + ih), (255, 255, 255), 2)
        inset_px = _env_positive_int("EXODIA_INV_CELL_INSET", 1)
        for row in range(INV_ROWS):
            for col in range(INV_COLS):
                rid = inventory_grid_cell_xywh(self.inventory_rect, row, col, inset_px)
                if rid is None:
                    continue
                sx, sy, sw, sh = rid
                filled = True
                if occ is not None and row < len(occ) and col < len(occ[row]):
                    filled = occ[row][col]
                color = (0, 200, 0) if filled else (0, 0, 220)
                overlay = vis.copy()
                cv2.rectangle(overlay, (sx, sy), (sx + sw, sy + sh), color, thickness=-1)
                cv2.addWeighted(overlay, 0.25, vis, 0.75, 0, vis)
                cv2.rectangle(vis, (sx, sy), (sx + sw, sy + sh), color, thickness=1)
        return vis

    def random_color(self):
        return math.floor(255 * random.random())
    
    def cluster_color(self, label):
        """Deterministic BGR color per cluster ``label`` (stable across runs for the same label)."""
        h = (abs(int(label)) * 2654435761) % (256 * 256 * 256)
        r = (h & 255)
        g = (h >> 8) & 255
        b = (h >> 16) & 255
        return [int(b), int(g), int(r)]

    # Locates contours for BGR bands in ``boundaries``; returns one anchor point.
    def locate_color(self, boundaries=None, multi=True, cluster_dist=25):
        """Find dominant color blob. With ``multi``, returns ``[[gx, gy]]`` in screen coords; else ``[[lx, ly]]`` in client-local coords from centroid of all contour points."""
        if boundaries is None:
            boundaries = list(_DEFAULT_COLOR_BOUNDARIES)
        _image = copy.deepcopy(self.curr_client)
        _, contours = _mask_and_contours_bgr(_image, boundaries)

        if len(contours) == 0:
            return []

        if self._DEBUG:
            dbg = _image.copy()
            cv2.drawContours(dbg, contours, -1, color=(0, 0, 255), thickness=2)
            Env.debug_view(dbg, "Drawn contours")

        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)

        draw = _image.copy()
        draw = cv2.rectangle(draw, pt1=(x, y), pt2=(x + w, y + h), color=(0, 255, 0), thickness=2)
        draw = cv2.drawContours(draw, contours, 0, color=(0, 255, 0), thickness=2)
        mask = np.zeros(draw.shape[:2], np.uint8)
        avg_x = 0
        avg_y = 0
        count = 0

        for cont in contours:
            for cont_p in cont:
                count += 1
                avg_x += cont_p[0][0]
                avg_y += cont_p[0][1]

            if multi:
                x_c, y_c, w_c, h_c = cv2.boundingRect(cont)
                mid_y = y_c + int(round(h_c / 2))
                mid_x = x_c + int(round(w_c / 2))
                if 0 <= mid_y < mask.shape[0] and 0 <= mid_x < mask.shape[1]:
                    if mask[mid_y, mid_x] != 255:
                        mask[y_c : y_c + h_c, x_c : x_c + w_c] = 255
                        if x != x_c or y != y_c or w != w_c or h != h_c:
                            draw = cv2.rectangle(
                                draw,
                                pt1=(x_c, y_c),
                                pt2=(x_c + w_c, y_c + h_c),
                                color=(0, 0, 255),
                                thickness=2,
                            )

        if count > 0:
            avg_x = math.floor(avg_x / count)
            avg_y = math.floor(avg_y / count)
            if self._DEBUG:
                print([avg_x, avg_y])

        x_center = math.floor(x + w / 2)
        y_center = math.floor(y + h / 2)

        if self._DEBUG:
            print("Length of contours: %d" % (len(contours),))
            print(x, y, w, h)
            dbg2 = draw.copy()
            dbg2 = cv2.circle(dbg2, [avg_x, avg_y], 10, color=(0, 0, 255), thickness=3)
            Env.debug_view(dbg2, title="Found color")
            print([x_center + self.client_rect[0], y_center + self.client_rect[1]])

        if multi:
            return [[x_center + self.client_rect[0], y_center + self.client_rect[1]]]
        return [[avg_x, avg_y]]

    # Locates clustered contour points and picks a COM near gameplay anchor.
    def locate_cluster(
        self,
        boundaries=None,
        cluster_dist=40,
        draw_contours=True,
        draw_clusters=True,
        draw_lines=True,
        use_target=False,
        c_target=(0, 0),
    ):
        """Returns ``[gx, gy]`` screen coords for chosen cluster COM, or ``[]`` if none."""
        if boundaries is None:
            boundaries = list(_DEFAULT_COLOR_BOUNDARIES)
        _image = copy.deepcopy(self.curr_client)
        _, contours = _mask_and_contours_bgr(_image, boundaries)

        if len(contours) == 0:
            return []

        points = []
        for cont in contours:
            for cont_p in cont:
                points.append([cont_p[0][0], cont_p[0][1]])
        X = np.array(points)

        clustering = DBSCAN(eps=cluster_dist, min_samples=2).fit(X)
        labels = clustering.labels_

        by_label = {}
        for i, lbl in enumerate(labels):
            if lbl == -1:
                continue
            by_label.setdefault(int(lbl), []).append(points[i])

        if not by_label:
            return []

        ordered_labels = sorted(by_label.keys())
        com_clusters = []
        for lbl in ordered_labels:
            pts = by_label[lbl]
            avg_x = math.floor(sum(p[0] for p in pts) / len(pts))
            avg_y = math.floor(sum(p[1] for p in pts) / len(pts))
            com_clusters.append([avg_x, avg_y])

        unique_clusters = np.array(ordered_labels)

        if self._DEBUG and draw_clusters:
            print(clustering)
            print(clustering.labels_)
            c_image = copy.deepcopy(self.curr_client)
            integer_to_color = {int(lb): self.cluster_color(lb) for lb in unique_clusters}
            print(len(unique_clusters), " clusters found!")
            for ca in range(len(X)):
                ce = X[ca]
                lb = int(labels[ca])
                if lb == -1:
                    continue
                b, g, r = integer_to_color[lb]
                cv2.circle(
                    img=c_image,
                    center=[int(ce[0]), int(ce[1])],
                    radius=1,
                    color=(int(b), int(g), int(r)),
                    thickness=2,
                )
            Env.debug_view(c_image, "Clustering")

        if self._DEBUG and draw_contours:
            _image2 = copy.deepcopy(self.curr_client)
            cv2.drawContours(_image2, contours, -1, color=(0, 0, 255), thickness=2)
            Env.debug_view(_image2, "Drawn contours")

        com_image = copy.deepcopy(self.curr_client) if self._DEBUG else None

        dist_com = 99999.0
        closest_c = points[0][:]
        ref = self.local_center if use_target else list(c_target)
        for _c in points:
            if self._DEBUG and draw_lines and com_image is not None:
                cv2.circle(img=com_image, center=_c, radius=5, color=(255, 255, 255), thickness=2)
                cv2.line(com_image, tuple(map(int, ref)), tuple(map(int, _c)), color=(255, 255, 255), thickness=1)
            _dist = math.dist(ref, _c)
            if _dist < dist_com:
                closest_c = _c
                dist_com = _dist

        dist_com = 99999.0
        closest_com = com_clusters[0]
        for com in com_clusters:
            if self._DEBUG and draw_lines and com_image is not None:
                cv2.circle(img=com_image, center=com, radius=5, color=(0, 0, 255), thickness=2)
                cv2.line(
                    com_image,
                    tuple(map(int, closest_c)),
                    tuple(map(int, com)),
                    color=(0, 0, 255),
                    thickness=2,
                )
            _dist = math.dist(closest_c, com)
            if _dist < dist_com:
                closest_com = com
                dist_com = _dist

        if self._DEBUG and draw_lines and com_image is not None:
            cv2.line(
                com_image,
                tuple(map(int, self.local_center)),
                tuple(map(int, closest_com)),
                color=(0, 255, 0),
                thickness=2,
            )
            print(closest_com)
            Env.debug_view(com_image, "Cluster cms to center")

        return [closest_com[0] + self.client_rect[0], closest_com[1] + self.client_rect[1]]

    def locate_image_detailed(
        self,
        inv: bool = False,
        filename: str = "",
        threshold: float = 0.8,
        name: str = "Screenshot",
        search_roi: Optional[List[int]] = None,
        max_peaks: int = 32,
    ) -> LocateImageResult:
        """
        Template match via ``TM_CCOEFF_NORMED`` with peak NMS. Returns structured result including scores.

        * ``client_xy`` — center in **client image** coordinates when ``inv=False``, else in **inventory crop** coordinates.
        """
        if inv:
            if self.curr_inventory is None or getattr(self.curr_inventory, "size", 0) == 0:
                self.grab_inventory()
            if self.curr_inventory is None or self.curr_inventory.size == 0:
                return LocateImageResult(filename, False, "no_inventory_crop", [])
            img_rgb = copy.deepcopy(self.curr_inventory)
        else:
            img_rgb = copy.deepcopy(self.curr_client)
        try:
            if img_rgb is None or img_rgb.size == 0:
                return LocateImageResult(filename, False, "empty_image", [])
            img_gray = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)
            off_x, off_y = 0, 0
            if search_roi is not None and len(search_roi) == 4:
                h0, w0 = img_gray.shape[:2]
                sx, sy, sw, sh = _clamp_roi(w0, h0, search_roi)
                img_gray = img_gray[sy : sy + sh, sx : sx + sw]
                img_rgb = img_rgb[sy : sy + sh, sx : sx + sw]
                off_x, off_y = sx, sy
            template_path = os.path.join(os.getcwd(), "images", filename)
            template = _load_template_gray(template_path)
            if template is None:
                if self._DEBUG:
                    print("locate_image: missing template images/", filename, sep="")
                return LocateImageResult(filename, False, "missing_template", [])
            tw, th = template.shape[::-1]
            res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
            peaks = _match_template_peaks(res, tw, th, threshold, max_peaks=max_peaks)
            if not peaks:
                if self._DEBUG:
                    Env.debug_view(img_rgb, "View image")
                    print("Locate image could not find the image ", filename)
                return LocateImageResult(filename, False, None, [])
            ox = self.inventory_global[0] if inv else self.client_rect[0]
            oy = self.inventory_global[1] if inv else self.client_rect[1]
            matches: List[TemplateMatch] = []
            for px, py, score in peaks:
                if self._DEBUG:
                    cv2.rectangle(img_rgb, (px, py), (px + tw, py + th), (255, 0, 0), thickness=1)
                cx_src = px + off_x + math.floor(tw / 2)
                cy_src = py + off_y + math.floor(th / 2)
                gcx = px + off_x + math.floor(tw / 2) + ox
                gcy = py + off_y + math.floor(th / 2) + oy
                matches.append(
                    TemplateMatch(screen_xy=[int(gcx), int(gcy)], client_xy=[int(cx_src), int(cy_src)], score=score)
                )
                if self._DEBUG:
                    cv2.circle(
                        img_rgb,
                        (px + math.floor(tw / 2), py + math.floor(th / 2)),
                        radius=min(math.floor(tw / 3), math.floor(th / 3)),
                        color=(0, 255, 0),
                        thickness=1,
                    )
            if self._DEBUG:
                Env.debug_view(img_rgb, "View image")
            return LocateImageResult(filename, True, None, matches)
        except Exception as exc:
            print("Locate image failed! %s (inv=%s file=%s)" % (exc, inv, filename))
            return LocateImageResult(filename, False, "exception", [])

    # search_roi: optional [x, y, w, h] within client or inventory image to limit matchTemplate cost
    def locate_image(self, inv=False, filename="", threshold=0.8, name="Screenshot", search_roi=None):
        """Return list of ``[gx, gy]`` match centers in screen coordinates (may be empty)."""
        detailed = self.locate_image_detailed(
            inv=inv, filename=filename, threshold=threshold, name=name, search_roi=search_roi
        )
        return [m.screen_xy[:] for m in detailed.matches]
    # Locate an image within the client scene by attempting to match based on features
    def find_image_in_scene(self, image_path):
        """ORB + homography: returns projected template center ``[gx, gy]`` in screen coords, or ``None``."""
        self.update()
        img_rgb = copy.deepcopy(self.curr_client)

        image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            print("find_image_in_scene: could not load", image_path)
            return None
        scene = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)

        if self._DEBUG:
            Env.debug_view(image)
            Env.debug_view(scene)

        orb = cv2.ORB_create()
        keypoints_image, descriptors_image = orb.detectAndCompute(image, None)
        keypoints_scene, descriptors_scene = orb.detectAndCompute(scene, None)

        if (
            descriptors_image is None
            or descriptors_scene is None
            or len(descriptors_image) < 2
            or len(descriptors_scene) < 2
        ):
            print("find_image_in_scene: insufficient descriptors")
            return None

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(descriptors_image, descriptors_scene)

        MIN_MATCH_COUNT = 10
        if len(matches) < MIN_MATCH_COUNT:
            print("Not enough matches are found - %d/%d" % (len(matches), MIN_MATCH_COUNT))
            return None

        src_pts = np.float32([keypoints_image[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([keypoints_scene[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

        M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        if M is None:
            print("find_image_in_scene: homography failed")
            return None

        matches_mask = mask.ravel().tolist()

        draw_params = dict(matchColor=(0, 255, 0), singlePointColor=None, matchesMask=matches_mask, flags=2)
        result_img = cv2.drawMatches(image, keypoints_image, scene, keypoints_scene, matches, None, **draw_params)

        if self._DEBUG:
            Env.debug_view(result_img, "Detecting image in scene")

        ih, iw = image.shape[:2]
        corners = np.float32([[0, 0], [iw, 0], [iw, ih], [0, ih]]).reshape(-1, 1, 2)
        projected = cv2.perspectiveTransform(corners, M)
        cx = float(np.mean(projected[:, 0, 0]))
        cy = float(np.mean(projected[:, 0, 1]))
        return [cx + self.client_rect[0], cy + self.client_rect[1]]

    def ocr_action_text_roi(self, psm: int = 7, scale: Optional[float] = None) -> Dict[str, Any]:
        """OCR on the action-text strip (client-local ROI ``_ACTION_STRIP_RECT_CLIENT``)."""
        src = self._client_bgr_for_text_crops()
        if src is None:
            return {"roi": "action_strip", "text": "", "error": "no_client_frame"}
        h0, w0 = src.shape[:2]
        roi = list(self.action_strip_roi_client())
        sx, sy, sw, sh = _clamp_roi(w0, h0, roi)
        crop = src[sy : sy + sh, sx : sx + sw]
        text = run_ocr(crop, psm=psm, scale=scale)
        return {
            "roi": "action_strip",
            "rect_client_local": [sx, sy, sw, sh],
            "text": text,
        }

    def ocr_dialogue_roi(self, psm: int = 6, scale: Optional[float] = 0.75) -> Dict[str, Any]:
        """OCR on the bottom chat strip defined by ``chat_rect`` (client-local)."""
        src = self._client_bgr_for_text_crops()
        if src is None:
            return {"roi": "dialogue_chat_strip", "text": "", "error": "no_client_frame"}
        if self.chat_rect is None or len(self.chat_rect) != 4:
            return {"roi": "dialogue_chat_strip", "text": "", "error": "no_chat_rect"}
        h0, w0 = src.shape[:2]
        sx, sy, sw, sh = _clamp_roi(w0, h0, self.chat_rect)
        crop = src[sy : sy + sh, sx : sx + sw]
        text = run_ocr(crop, psm=psm, scale=scale)
        return {
            "roi": "dialogue_chat_strip",
            "rect_client_local": [sx, sy, sw, sh],
            "text": text,
        }

    def _action_text_color_code_from_resized(self, img: np.ndarray) -> int:
        """Tri-state from green vs red contour heuristics on resized action-strip BGR image."""
        if self._DEBUG:
            Env.debug_view(img)

        boundaries = [([0, 250, 0], [10, 255, 10])]
        boundaries_not = [([0, 0, 250], [10, 10, 255])]
        for (lower, upper) in boundaries:
            lower = np.array(lower, dtype="uint8")
            upper = np.array(upper, dtype="uint8")
            img_g = copy.deepcopy(img)
            mask_g = cv2.inRange(img_g, lower, upper)
            output = cv2.bitwise_and(img_g, img_g, mask=mask_g)
            ret, thresh_g = cv2.threshold(mask_g, 40, 255, 0)

        for (lower, upper) in boundaries_not:
            lower = np.array(lower, dtype="uint8")
            upper = np.array(upper, dtype="uint8")
            img_r = copy.deepcopy(img)
            mask_r = cv2.inRange(img_r, lower, upper)
            output = cv2.bitwise_and(img_r, img_r, mask=mask_r)
            ret, thresh_r = cv2.threshold(mask_r, 40, 255, 0)

        rect_kernel_g = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
        rect_kernel_r = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))

        dilation_g = cv2.dilate(thresh_g, rect_kernel_g, iterations=1)
        dilation_r = cv2.dilate(thresh_r, rect_kernel_r, iterations=1)

        contours_g, hierarchy = cv2.findContours(dilation_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        contours_r, hierarchy = cv2.findContours(dilation_r, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if self._DEBUG:
            if len(contours_g) > 0:
                draw_contour = cv2.drawContours(copy.deepcopy(img), contours_g, 0, color=(255, 0, 0), thickness=2)
                Env.debug_view(draw_contour, "Contours Acting")
            if len(contours_r) > 0:
                draw_contour = cv2.drawContours(copy.deepcopy(img), contours_r, 0, color=(255, 0, 0), thickness=2)
                Env.debug_view(draw_contour, "Contours NOT Acting")

        im2 = img.copy()
        im3 = img.copy()

        working = False
        not_working = False

        for cnt in contours_g:
            x, y, w, h = cv2.boundingRect(cnt)
            cropped = im2[y : y + h, x : x + w]
            working = True

            if self._DEBUG:
                rect = cv2.rectangle(im2, (x, y), (x + w, y + h), (0, 255, 0), 2)
                print("(GREEN) WE ARE WORKING")
                Env.debug_view(rect)

        for cnt in contours_r:
            x, y, w, h = cv2.boundingRect(cnt)
            cropped = im3[y : y + h, x : x + w]
            not_working = True

            if self._DEBUG:
                rect = cv2.rectangle(im3, (x, y), (x + w, y + h), (0, 255, 0), 2)
                print("(RED) WE ARE NOT WORKING")
                Env.debug_view(rect)

        result = 2
        if working:
            result = 0
        elif not_working:
            result = 1
        return result

    def find_action_strip_rect(
        self,
        threshold: float = 0.22,
        *,
        refresh_client: bool = True,
    ) -> Optional[List[int]]:
        """
        Locate the skilling action box via ``Fishing_text`` / ``Not_fishing_text`` in the
        bottom-right UI band. Sets ``action_strip_rect`` when found.
        """
        if refresh_client or self.curr_client is None:
            self.check_client()
        src = self._client_bgr_for_text_crops()
        if src is None or src.size == 0:
            self.action_strip_rect = None
            return None
        h0, w0 = src.shape[:2]
        search_roi = _bottom_right_ui_search_roi(w0, h0)
        gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        sx, sy, sw, sh = _clamp_roi(w0, h0, search_roi)
        patch = gray[sy : sy + sh, sx : sx + sw]
        box_w = int(os.environ.get("EXODIA_ACTION_STRIP_WIDTH", "100"))
        box_h = int(os.environ.get("EXODIA_ACTION_STRIP_HEIGHT", "30"))
        best: Optional[Tuple[float, int, int]] = None
        for filename in ("Fishing_text.png", "Not_fishing_text.png"):
            template = _load_template_gray(os.path.join(os.getcwd(), "images", filename))
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
            self.action_strip_rect = None
            return None
        _, cx, cy = best
        ax = max(0, cx - int(box_w * 0.12))
        ay = max(0, cy - int(box_h * 0.35))
        if ax + box_w > w0:
            ax = max(0, w0 - box_w)
        if ay + box_h > h0:
            ay = max(0, h0 - box_h)
        self.action_strip_rect = [ax, ay, box_w, box_h]
        return self.action_strip_rect

    def action_strip_roi_client(self) -> Tuple[int, int, int, int]:
        """Action line ROI — template-found box, else left/bottom of inventory."""
        if self.action_strip_rect is None or len(self.action_strip_rect) != 4:
            self.find_action_strip_rect(refresh_client=False)
        if self.action_strip_rect is not None and len(self.action_strip_rect) == 4:
            return tuple(int(v) for v in self.action_strip_rect)
        if self.inventory_rect is None or len(self.inventory_rect) != 4:
            self.find_inventory(refresh_client=False)
        fw, fh = (0, 0)
        src = self._client_bgr_for_text_crops()
        if src is not None and src.size > 0:
            fh, fw = src.shape[:2]
        rect = resolve_action_strip_roi_client(
            inventory_rect=self.inventory_rect,
            frame_w=fw,
            frame_h=fh,
        )
        return tuple(rect)

    def _action_strip_bgr(self) -> Optional[np.ndarray]:
        """Crop the skilling action line (left of inventory) from the client frame."""
        src = self._client_bgr_for_text_crops()
        if src is None or src.size == 0:
            return None
        ax, ay, aw, ah = self.action_strip_roi_client()
        h0, w0 = src.shape[:2]
        sx, sy, sw, sh = _clamp_roi(w0, h0, [ax, ay, aw, ah])
        return src[sy : sy + sh, sx : sx + sw].copy()

    def get_action_text(self, refresh: bool = True) -> int:
        """
        Heuristic action line state from **color contour** detection (not full OCR).

        Returns:
            **0** — green-styled region suggests an active skill action line.
            **1** — red-styled region suggests idle/other action line.
            **2** — fishing action strip not detected (often hidden until you fish recently).

        ROI is placed **left of the inventory** when ``inventory_rect`` is calibrated
        (override with ``EXODIA_ACTION_STRIP_RECT`` or ``EXODIA_ACTION_STRIP_LEFT_OF_INV=0``).

        Args:
            refresh: If ``True`` (default), calls ``update()`` first. If ``False``, crops
                the action strip from the current ``curr_client`` frame.
        """
        if refresh:
            self.update()
        else:
            self.find_action_strip_rect(refresh_client=False)
        return self._action_text_color_code_from_strip()

    def get_action_text_robust(
        self, refresh: bool = True, template_threshold: float = 0.26
    ) -> int:
        """
        ``get_action_text`` with template fallback on the **action strip ROI only**.

        If the player has not fished recently, the Fishing / NOT fishing strip is
        usually hidden — color and templates both return **2** (no UI). Callers
        should seek a fishing spot, not wait in FISHING state.
        """
        if refresh:
            self.update()
        else:
            self.find_action_strip_rect(refresh_client=False)

        code = self._action_text_color_code_from_strip()
        if code != 2:
            return code

        fish_s, idle_s = self._action_template_scores_in_strip()
        if fish_s >= template_threshold and fish_s >= idle_s:
            return 0
        if idle_s >= template_threshold and idle_s > fish_s:
            return 1

        fish_s2, idle_s2 = self._action_template_scores_in_bottom_ui()
        thr = float(
            os.environ.get(
                "EXODIA_ACTION_TEMPLATE_THRESHOLD",
                str(template_threshold),
            )
        )
        if fish_s2 >= thr and fish_s2 >= idle_s2:
            return 0
        if idle_s2 >= thr and idle_s2 > fish_s2:
            return 1
        return 2

    def _action_text_color_code_from_strip(self) -> int:
        strip = self._action_strip_bgr()
        if strip is None or strip.size == 0:
            return 2
        img = Env.resize_image(strip, 300)
        return self._action_text_color_code_from_resized(img)

    def _action_template_scores_in_strip(self) -> Tuple[float, float]:
        strip = self._action_strip_bgr()
        if strip is None or strip.size == 0:
            return 0.0, 0.0
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        return self._action_template_scores_on_gray(gray)

    def _action_template_scores_in_bottom_ui(self) -> Tuple[float, float]:
        src = self._client_bgr_for_text_crops()
        if src is None or src.size == 0:
            return 0.0, 0.0
        h0, w0 = src.shape[:2]
        sx, sy, sw, sh = _clamp_roi(w0, h0, _bottom_right_ui_search_roi(w0, h0))
        patch = cv2.cvtColor(src[sy : sy + sh, sx : sx + sw], cv2.COLOR_BGR2GRAY)
        return self._action_template_scores_on_gray(patch)

    def _action_template_scores_on_gray(self, gray: np.ndarray) -> Tuple[float, float]:
        scores = {0: 0.0, 1: 0.0}
        for filename, result_code in (
            ("Fishing_text.png", 0),
            ("Not_fishing_text.png", 1),
        ):
            path = os.path.join(os.getcwd(), "images", filename)
            template = _load_template_gray(path)
            if template is None:
                continue
            th, tw = template.shape[:2]
            if gray.shape[0] < th or gray.shape[1] < tw:
                continue
            res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            scores[result_code] = max(scores[result_code], float(max_val))
        return scores[0], scores[1]

    def get_action_text_with_ocr(self, refresh: bool = True) -> Tuple[int, Dict[str, Any]]:
        """
        Same tri-state as ``get_action_text``, plus ``ocr_action_text_roi()`` on ``curr_client``.

        If ``refresh`` is ``True``, ``get_action_text`` runs first (includes ``update()``).
        """
        code = self.get_action_text(refresh=refresh)
        ocr_meta = self.ocr_action_text_roi()
        return code, ocr_meta
    
#Main
if __name__ == "__main__":
    bot_eyes = BotEyes()