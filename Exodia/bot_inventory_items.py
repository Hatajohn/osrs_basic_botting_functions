"""
Per-slot inventory item identification via template match against ``items/*.png``.

Template filenames (stem) become item names, e.g. ``items/flax.png`` → ``"flax"``.
Occupied slots with no match above threshold are labeled ``"?"``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_eyes import INV_COLS, INV_ROWS, inventory_grid_cell_xywh
from bot_inventory_count import _slot_template_score
from bot_inventory_detect import draw_inventory_occupancy_overlay

_EXODIA_DIR = Path(__file__).resolve().parent
_DEFAULT_ITEMS_DIR = _EXODIA_DIR / "items"
_UNKNOWN_LABEL = "?"


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def items_directory() -> Path:
    raw = os.environ.get("EXODIA_ITEMS_DIR", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_EXODIA_DIR / p).resolve()
    return _DEFAULT_ITEMS_DIR.resolve()


def load_item_templates(
    items_dir: Optional[Path] = None,
) -> Dict[str, np.ndarray]:
    """Load ``*.png`` templates as grayscale arrays keyed by lowercase stem."""
    root = items_dir if items_dir is not None else items_directory()
    if not root.is_dir():
        return {}
    out: Dict[str, np.ndarray] = {}
    for path in sorted(root.glob("*.png")):
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0:
            continue
        name = path.stem.strip().lower()
        if not name:
            continue
        out[name] = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return out


def match_cell_to_item(
    cell_bgr: np.ndarray,
    templates: Dict[str, np.ndarray],
    *,
    threshold: Optional[float] = None,
) -> Tuple[Optional[str], float]:
    """
    Best template match for one slot crop.

    Returns ``(item_name, score)`` when ``score >= threshold``, else ``(None, best_score)``.
    """
    if cell_bgr is None or cell_bgr.size == 0 or not templates:
        return None, 0.0
    thr = threshold if threshold is not None else _env_float("EXODIA_INV_ITEM_MATCH_THRESHOLD", 0.40)
    best_name: Optional[str] = None
    best_score = 0.0
    for name, tpl in templates.items():
        score = _slot_template_score(cell_bgr, tpl)
        if score > best_score:
            best_score = score
            best_name = name
    if best_name is not None and best_score >= thr:
        return best_name, best_score
    return None, best_score


def _item_match_inset_px(inventory_rect: Sequence[int]) -> int:
    """Inset for slot crops used in template match (0 = full tile; allows sub-pixel slide)."""
    raw = os.environ.get("EXODIA_INV_ITEM_MATCH_INSET", "0").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return 0


def identify_inventory_slot_items(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    occupancy: Sequence[Sequence[bool]],
    *,
    templates: Optional[Dict[str, np.ndarray]] = None,
    items_dir: Optional[Path] = None,
    threshold: Optional[float] = None,
) -> Tuple[Optional[List[List[Optional[str]]]], Dict[Tuple[int, int], float]]:
    """
    Map occupied slots to item names from ``items/`` templates.

    Returns ``(grid_7x4, scores)`` where grid cells are:
    ``None`` = empty slot, ``"?"`` = occupied but unknown, else the template stem.
    ``scores[(row,col)]`` is the best match score for occupied slots.
    """
    if client_bgr is None or client_bgr.size == 0 or len(inventory_rect) != 4:
        return None, {}
    tpl = templates if templates is not None else load_item_templates(items_dir)
    rect = tuple(int(v) for v in inventory_rect[:4])
    match_inset = _item_match_inset_px(rect)
    grid: List[List[Optional[str]]] = []
    scores: Dict[Tuple[int, int], float] = {}
    for row in range(INV_ROWS):
        row_out: List[Optional[str]] = []
        for col in range(INV_COLS):
            occupied = (
                row < len(occupancy)
                and col < len(occupancy[row])
                and bool(occupancy[row][col])
            )
            if not occupied:
                row_out.append(None)
                continue
            cell = inventory_grid_cell_xywh(rect, row, col, match_inset)
            if cell is None:
                row_out.append(_UNKNOWN_LABEL)
                continue
            x, y, w, h = cell
            crop = client_bgr[y : y + h, x : x + w]
            name, score = match_cell_to_item(crop, tpl, threshold=threshold)
            scores[(row, col)] = float(score)
            row_out.append(name if name is not None else _UNKNOWN_LABEL)
        grid.append(row_out)
    return grid, scores


def draw_inventory_item_identify_overlay(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Optional[Sequence[Sequence[bool]]] = None,
    *,
    label_color_bgr: Tuple[int, int, int] = (0, 255, 0),
    unknown_color_bgr: Tuple[int, int, int] = (0, 255, 255),
) -> np.ndarray:
    """
    Same base as ``inventory_test_overlay``: occupancy tint + grid, plus item labels
    on occupied slots (name or ``?``).
    """
    vis = draw_inventory_occupancy_overlay(
        client_bgr, inventory_rect, occupancy, draw_panel_outline=True
    )
    rect = tuple(int(v) for v in inventory_rect[:4])
    font = cv2.FONT_HERSHEY_SIMPLEX
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if row >= len(slot_items) or col >= len(slot_items[row]):
                continue
            label = slot_items[row][col]
            if label is None:
                continue
            cell = inventory_grid_cell_xywh(rect, row, col, 0)
            if cell is None:
                continue
            x, y, w, h = cell
            color = unknown_color_bgr if label == _UNKNOWN_LABEL else label_color_bgr
            text = label if len(label) <= 10 else label[:9] + "…"
            scale = max(0.4, min(0.6, w / 80.0))
            thickness = 1
            (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
            tx = x + max(2, (w - tw) // 2)
            ty = y + max(th + 2, (h + th) // 2)
            cv2.putText(vis, text, (tx, ty), font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
            cv2.putText(vis, text, (tx, ty), font, scale, color, thickness, cv2.LINE_AA)
    return vis
