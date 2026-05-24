"""
Per-slot inventory item identification via template match against ``items/*.png``.

Named templates: ``items/flax.png`` → ``"flax"``.
Unmatched occupied slots: ``unknown:<8-hex>`` when ``EXODIA_SEEN_ITEMS=1``, else ``"?"``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_eyes import INV_COLS, INV_ROWS, inventory_grid_cell_xywh
from bot_inventory_detect import draw_inventory_occupancy_overlay
from bot_match_index import (
    MatchSignals,
    MatchVerdict,
    TemplateCatalog,
    SeenItemRegistry,
    extract_signals,
    is_unknown_label,
    is_temp_item_id,
    load_named_catalog,
    load_seen_registry,
    seen_id_from_label,
)
from bot_match_index import _hist_l1

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


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def items_directory() -> Path:
    raw = os.environ.get("EXODIA_ITEMS_DIR", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_EXODIA_DIR / p).resolve()
    return _DEFAULT_ITEMS_DIR.resolve()


def load_item_templates(
    items_dir: Optional[Path] = None,
) -> Dict[str, np.ndarray]:
    """Load named ``*.png`` templates as grayscale (excludes 8-char temp-id stems)."""
    root = items_dir if items_dir is not None else items_directory()
    if not root.is_dir():
        return {}
    out: Dict[str, np.ndarray] = {}
    for path in sorted(root.glob("*.png")):
        stem = path.stem.strip().lower()
        if not stem or is_temp_item_id(stem):
            continue
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0:
            continue
        out[stem] = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return out


def load_item_catalog(items_dir: Optional[Path] = None) -> TemplateCatalog:
    return load_named_catalog(items_dir)


def resolve_cell_item(
    cell_bgr: np.ndarray,
    catalog: TemplateCatalog,
    seen_registry: Optional[SeenItemRegistry],
    *,
    threshold: Optional[float] = None,
    frame_seen_ids: Optional[Dict[str, MatchSignals]] = None,
    frame_bumped: Optional[set] = None,
) -> Tuple[Optional[str], float, Optional[MatchVerdict], bool]:
    """
    Returns ``(label, score, verdict, created_temp)``.

    ``label`` is a named stem, ``unknown:<id>``, or ``None`` (caller maps to ``?``).
    """
    if cell_bgr is None or cell_bgr.size == 0:
        return None, 0.0, None, False

    verdict = catalog.match_query(cell_bgr, threshold=threshold)
    if verdict.accepted and verdict.best_name:
        return verdict.best_name, verdict.best_score, verdict, False

    if not _env_bool("EXODIA_SEEN_ITEMS", False) or seen_registry is None:
        return None, verdict.best_score, verdict, False

    sig_q = verdict.query_signals if verdict.query_signals is not None else extract_signals(cell_bgr)
    if (
        _env_bool("EXODIA_SEEN_FRAME_DEDUPE", True)
        and frame_seen_ids is not None
        and sig_q is not None
    ):
        dhash_thr = int(os.environ.get("EXODIA_SEEN_DHASH_MAX_BITS", "10"))
        color_thr = float(os.environ.get("EXODIA_SEEN_COLOR_MAX_L1", "0.40"))
        for tid, stored_sig in frame_seen_ids.items():
            if (sig_q.dhash ^ stored_sig.dhash).bit_count() > dhash_thr:
                continue
            if _hist_l1(stored_sig.hue_hist, sig_q.hue_hist) > color_thr:
                continue
            if frame_bumped is None or tid not in frame_bumped:
                seen_registry._increment_sidecar(tid)
                if frame_bumped is not None:
                    frame_bumped.add(tid)
            return (
                seen_registry.label_for(tid),
                verdict.best_score,
                verdict,
                False,
            )

    label, seen_verdict, created = seen_registry.resolve(cell_bgr, threshold=threshold)
    combined = seen_verdict if seen_verdict.candidates else verdict
    frame_tid = seen_verdict.best_name if seen_verdict.best_name else seen_id_from_label(label or "")
    if (
        frame_seen_ids is not None
        and combined.query_signals is not None
        and frame_tid
    ):
        if created or frame_tid not in frame_seen_ids:
            frame_seen_ids[frame_tid] = combined.query_signals
            if frame_bumped is not None and created:
                frame_bumped.add(frame_tid)
        elif not created and frame_tid not in frame_seen_ids:
            frame_seen_ids[frame_tid] = combined.query_signals
            if frame_bumped is not None:
                frame_bumped.add(frame_tid)

    score = seen_verdict.best_score if seen_verdict.best_score > 0 else verdict.best_score
    return label, score, combined, created


def match_cell_to_item(
    cell_bgr: np.ndarray,
    templates: Dict[str, np.ndarray],
    *,
    threshold: Optional[float] = None,
    catalog: Optional[TemplateCatalog] = None,
    seen_registry: Optional[SeenItemRegistry] = None,
) -> Tuple[Optional[str], float]:
    """
    Best template match for one slot crop.

    Returns ``(item_name, score)`` when accepted, else ``(None, best_score)``.
    Legacy dict ``templates`` used when ``catalog`` is omitted.
    """
    cat = catalog
    if cat is None:
        cat = load_named_catalog(root)

    label, score, _, _ = resolve_cell_item(
        cell_bgr, cat, seen_registry, threshold=threshold
    )
    thr = threshold if threshold is not None else _env_float("EXODIA_INV_ITEM_MATCH_THRESHOLD", 0.40)
    if label and not is_unknown_label(label) and not label.startswith("unknown:"):
        if score >= thr:
            return label, score
    if label and label.startswith("unknown:"):
        return label, score
    return None, score


def _item_match_inset_px(inventory_rect: Sequence[int]) -> int:
    """Inset for slot crops used in template match (0 = full tile; allows sub-pixel slide)."""
    raw = os.environ.get("EXODIA_INV_ITEM_MATCH_INSET", "0").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return 0


def _match_debug_enabled() -> bool:
    return _env_bool("EXODIA_MATCH_DEBUG", False)


def _dump_debug_slot(crop: np.ndarray, row: int, col: int) -> None:
    out_dir = _EXODIA_DIR / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("debug_slot_%d_%d.png" % (row, col))
    cv2.imwrite(str(path), crop)


def identify_inventory_slot_items(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    occupancy: Sequence[Sequence[bool]],
    *,
    templates: Optional[Dict[str, np.ndarray]] = None,
    items_dir: Optional[Path] = None,
    threshold: Optional[float] = None,
    catalog: Optional[TemplateCatalog] = None,
    seen_registry: Optional[SeenItemRegistry] = None,
    return_diagnostics: bool = False,
) -> Tuple[
    Optional[List[List[Optional[str]]]],
    Dict[Tuple[int, int], float],
    Optional[Dict[Tuple[int, int], Dict[str, Any]]],
]:
    """
    Map occupied slots to item names from ``items/`` templates.

    Returns ``(grid_7x4, scores, diagnostics_or_None)`` where grid cells are:
    ``None`` = empty, ``unknown:<id>`` or ``"?"`` = occupied unknown, else named stem.
    """
    if client_bgr is None or client_bgr.size == 0 or len(inventory_rect) != 4:
        empty_diag: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = {} if return_diagnostics else None
        return None, {}, empty_diag

    root = items_dir if items_dir is not None else items_directory()
    cat = catalog if catalog is not None else load_item_catalog(root)
    if templates is not None and catalog is None:
        _ = templates  # legacy callers may pass; catalog loaded from disk

    seen = seen_registry
    if seen is None and _env_bool("EXODIA_SEEN_ITEMS", False):
        seen = load_seen_registry(root)

    rect = tuple(int(v) for v in inventory_rect[:4])
    match_inset = _item_match_inset_px(rect)
    grid: List[List[Optional[str]]] = []
    scores: Dict[Tuple[int, int], float] = {}
    diagnostics: Dict[Tuple[int, int], Dict[str, Any]] = {}
    frame_seen: Dict[str, MatchSignals] = {}
    frame_dedupe = _env_bool("EXODIA_SEEN_FRAME_DEDUPE", True)
    frame_bumped: set = set()

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
            if _match_debug_enabled():
                _dump_debug_slot(crop, row, col)

            label, score, verdict, created = resolve_cell_item(
                crop,
                cat,
                seen,
                threshold=threshold,
                frame_seen_ids=frame_seen if frame_dedupe else None,
                frame_bumped=frame_bumped if frame_dedupe else None,
            )
            scores[(row, col)] = float(score)

            if label is None:
                row_out.append(_UNKNOWN_LABEL)
            elif label.startswith("unknown:"):
                tid = seen_id_from_label(label)
                if created and tid:
                    frame_bumped.add(tid)
                row_out.append(label)
            else:
                row_out.append(label)

            if return_diagnostics and verdict is not None:
                diagnostics[(row, col)] = {
                    "verdict": verdict.to_dict(),
                    "created": created,
                    "reject": verdict.rejection_summary(),
                }
        grid.append(row_out)

    diag_out = diagnostics if return_diagnostics else None
    return grid, scores, diag_out


def _overlay_label_text(label: str) -> str:
    if label.startswith("unknown:"):
        tid = seen_id_from_label(label) or label
        return tid if len(tid) <= 10 else tid[:8]
    if label == _UNKNOWN_LABEL:
        return label
    return label if len(label) <= 10 else label[:7] + "..."


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
    on occupied slots (name, ``unknown:<id>``, or ``?``).
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
            is_unk = label == _UNKNOWN_LABEL or label.startswith("unknown:")
            color = unknown_color_bgr if is_unk else label_color_bgr
            text = _overlay_label_text(label)
            scale = max(0.28, min(0.38, w / 120.0))
            thickness = 1
            (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
            pad_x, pad_y = 2, 2
            tx = x + pad_x
            ty = y + h - pad_y - max(0, baseline)
            cv2.putText(vis, text, (tx, ty), font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
            cv2.putText(vis, text, (tx, ty), font, scale, color, thickness, cv2.LINE_AA)
    return vis
