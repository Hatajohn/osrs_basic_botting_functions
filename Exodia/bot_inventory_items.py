"""
Per-slot inventory item identification via template match against ``items/*.png``.

Named templates: ``items/flax.png`` → ``"flax"``.
Unmatched occupied slots: ``unknown:<8-hex>`` when ``EXODIA_SEEN_ITEMS=1``, else ``"?"``.
Frame-local fingerprint buckets (tests / ``EXODIA_INV_FRAME_BUCKETS=1``): ``tmp:<8-hex>``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_eyes import INV_COLS, INV_ROWS, inventory_grid_cell_xywh
from bot_inventory_count import _slot_gray_for_match, _slot_template_score, _strip_runelite_tags_bgr
from bot_inventory_detect import draw_inventory_occupancy_overlay
from bot_match_index import (
    MatchSignals,
    MatchVerdict,
    TemplateCatalog,
    SeenItemRegistry,
    _hist_l1,
    allocate_temp_id,
    extract_signals,
    is_unknown_label,
    is_temp_item_id,
    load_named_catalog,
    load_seen_registry,
    seen_id_from_label,
    signals_same_item,
)

_EXODIA_DIR = Path(__file__).resolve().parent
_DEFAULT_ITEMS_DIR = _EXODIA_DIR / "items"
_UNKNOWN_LABEL = "?"
_FRAME_BUCKET_PREFIX = "tmp:"


@dataclass(frozen=True)
class FrameFingerprintBucket:
    """One ephemeral item type in a single capture (not persisted to ``items/``)."""

    temp_id: str
    slots: Tuple[Tuple[int, int], ...]
    representative: Optional[MatchSignals] = None


def frame_bucket_label(temp_id: str) -> str:
    return _FRAME_BUCKET_PREFIX + temp_id.strip().lower()


def frame_bucket_id_from_label(label: Optional[str]) -> Optional[str]:
    if not label or not label.startswith(_FRAME_BUCKET_PREFIX):
        return None
    tid = label[len(_FRAME_BUCKET_PREFIX) :].strip().lower()
    return tid if is_temp_item_id(tid) else None


def is_frame_bucket_label(label: Optional[str]) -> bool:
    return frame_bucket_id_from_label(label) is not None


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


def _needs_frame_fingerprint_bucket(label: Optional[str]) -> bool:
    if label is None or label == _UNKNOWN_LABEL:
        return True
    if label.startswith("unknown:"):
        return False
    if is_frame_bucket_label(label):
        return False
    return is_unknown_label(label)


def _bucket_template_min() -> float:
    return _env_float("EXODIA_BUCKET_TEMPLATE_MIN", 0.38)


def _bucket_use_seen_loose() -> bool:
    return _env_bool("EXODIA_BUCKET_USE_SEEN_LOOSE", True)


def _seen_loose_dhash_max() -> int:
    raw = os.environ.get("EXODIA_SEEN_DHASH_MAX_BITS", "10").strip()
    try:
        return int(raw)
    except ValueError:
        return 10


def _seen_loose_color_max() -> float:
    return _env_float("EXODIA_SEEN_COLOR_MAX_L1", 0.40)


def slots_match_for_bucket(
    crop_a: np.ndarray,
    crop_b: np.ndarray,
    *,
    sig_a: Optional[MatchSignals] = None,
    sig_b: Optional[MatchSignals] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Whether two slot BGR crops belong in the same fingerprint bucket.

    Tiers (first pass wins): symmetric ``signals_same_item``, template cross-score,
    optional seen-loose dHash+hue (``EXODIA_BUCKET_USE_SEEN_LOOSE``).
    """
    debug: Dict[str, Any] = {}
    if crop_a is None or crop_b is None or crop_a.size == 0 or crop_b.size == 0:
        return False, "empty_crop", debug

    sa = sig_a if sig_a is not None else extract_signals(crop_a)
    sb = sig_b if sig_b is not None else extract_signals(crop_b)

    same, distances, scores = signals_same_item(sa, sb)
    debug["signals"] = {"distances": distances, "scores": scores}
    if same:
        return True, "signals", debug

    gray_a = _slot_gray_for_match(crop_a)
    gray_b = _slot_gray_for_match(crop_b)
    t_min = _bucket_template_min()
    s_ab = _slot_template_score(crop_a, gray_b)
    s_ba = _slot_template_score(crop_b, gray_a)
    cross = min(s_ab, s_ba)
    debug["template"] = {"score_ab": s_ab, "score_ba": s_ba, "cross_min": cross, "min": t_min}
    if cross >= t_min:
        return True, "template", debug

    if _bucket_use_seen_loose():
        dhash_thr = _seen_loose_dhash_max()
        color_thr = _seen_loose_color_max()
        dhash_dist = float((sa.dhash ^ sb.dhash).bit_count())
        color_dist = _hist_l1(sa.hue_hist, sb.hue_hist)
        debug["seen_loose"] = {
            "dhash": dhash_dist,
            "dhash_max": dhash_thr,
            "color": color_dist,
            "color_max": color_thr,
        }
        if dhash_dist <= dhash_thr and color_dist <= color_thr:
            return True, "seen_loose", debug

    return False, "no_tier", debug


def apply_frame_fingerprint_buckets(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    occupancy: Sequence[Sequence[bool]],
    slot_items: List[List[Optional[str]]],
    *,
    inset: Optional[int] = None,
) -> Tuple[List[List[Optional[str]]], Dict[str, FrameFingerprintBucket]]:
    """
    Group occupied ``?`` slots into ephemeral ``tmp:<8-hex>`` labels by fingerprint.

    Named template hits and persistent ``unknown:<id>`` labels are left unchanged.
    """
    rect = tuple(int(v) for v in inventory_rect[:4])
    rep_crops: Dict[str, np.ndarray] = {}
    rep_sigs: Dict[str, MatchSignals] = {}
    slots_by_id: Dict[str, List[Tuple[int, int]]] = {}
    grid = [list(row) for row in slot_items]

    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if row >= len(occupancy) or col >= len(occupancy[row]) or not occupancy[row][col]:
                continue
            if row >= len(grid) or col >= len(grid[row]):
                continue
            label = grid[row][col]
            if not _needs_frame_fingerprint_bucket(label):
                continue

            crop = crop_inventory_slot_bgr(
                client_bgr, rect, row, col, inset=inset
            )
            if crop is None:
                continue
            sig = extract_signals(crop)

            matched_id: Optional[str] = None
            for tid, rep_crop in rep_crops.items():
                same, _reason, _dbg = slots_match_for_bucket(
                    rep_crop, crop, sig_a=rep_sigs.get(tid), sig_b=sig
                )
                if same:
                    matched_id = tid
                    break

            if matched_id is None:
                matched_id = allocate_temp_id(rep_crops.keys())
                rep_crops[matched_id] = crop.copy()
                rep_sigs[matched_id] = sig
                slots_by_id[matched_id] = []

            slots_by_id[matched_id].append((row, col))
            grid[row][col] = frame_bucket_label(matched_id)

    buckets = {
        tid: FrameFingerprintBucket(
            temp_id=tid,
            slots=tuple(slots_by_id.get(tid, ())),
            representative=rep_sigs.get(tid),
        )
        for tid in rep_crops
    }
    return grid, buckets


def slot_label_bucket_counts(
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Sequence[Sequence[bool]],
) -> List[Tuple[str, int]]:
    """
    Occupied-slot counts per label (named, ``tmp:``, ``unknown:``, or ``?``).

    Sorted by count descending, then label.
    """
    counts: Dict[str, int] = {}
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if row >= len(occupancy) or col >= len(occupancy[row]) or not occupancy[row][col]:
                continue
            if row >= len(slot_items) or col >= len(slot_items[row]):
                continue
            label = slot_items[row][col]
            if label is None:
                continue
            key = label
            counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(label, int(n)) for label, n in ordered]


def draw_inventory_bucket_counts_above(
    image: np.ndarray,
    inventory_rect: Sequence[int],
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Sequence[Sequence[bool]],
    *,
    font_px: int = 18,
    color_bgr: Tuple[int, int, int] = (0, 255, 0),
    line_gap: int = 4,
) -> np.ndarray:
    """Draw ``<label> x<count>`` lines just above the inventory panel."""
    counts = slot_label_bucket_counts(slot_items, occupancy)
    if not counts:
        return image

    vis = image
    ix, iy = int(inventory_rect[0]), int(inventory_rect[1])
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = font_px / 22.0
    thickness = 1
    line_step = font_px + line_gap

    lines: List[str] = []
    for label, n in counts:
        short = _overlay_label_text(label)
        lines.append("%s x%d" % (short, n))

    block_h = len(lines) * line_step
    y = max(font_px, iy - block_h - line_gap)

    for text in lines:
        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        _ = tw, th, baseline
        cv2.putText(
            vis,
            text,
            (ix, y),
            font,
            scale,
            (0, 0, 0),
            thickness + 2,
            cv2.LINE_AA,
        )
        cv2.putText(
            vis,
            text,
            (ix, y),
            font,
            scale,
            color_bgr,
            thickness,
            cv2.LINE_AA,
        )
        y += line_step
    return vis


def summarize_frame_fingerprint_buckets(
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Sequence[Sequence[bool]],
) -> List[str]:
    """Human-readable bucket lines for test logs."""
    by_id: Dict[str, List[Tuple[int, int]]] = {}
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if row >= len(occupancy) or col >= len(occupancy[row]) or not occupancy[row][col]:
                continue
            if row >= len(slot_items) or col >= len(slot_items[row]):
                continue
            tid = frame_bucket_id_from_label(slot_items[row][col])
            if tid:
                by_id.setdefault(tid, []).append((row, col))

    lines: List[str] = []
    for tid in sorted(by_id.keys()):
        slots = by_id[tid]
        lines.append(
            "fingerprint bucket %s: %d slots %s"
            % (frame_bucket_label(tid), len(slots), slots)
        )
    lines.insert(0, "fingerprint buckets: %d distinct tmp ids" % len(by_id))
    return lines


@dataclass(frozen=True)
class SlotSameItemVerdict:
    """Result of comparing two inventory slots for the same item type."""

    same: bool
    reason: str
    distances: Dict[str, float]
    scores: Dict[str, float]
    signals_a: Optional[MatchSignals] = None
    signals_b: Optional[MatchSignals] = None


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


def inventory_slot_cell_looks_occupied(cell_bgr: np.ndarray) -> bool:
    """
    Heuristic: occupied slot vs empty brown plate (no panel context required).

    Mirrors occupancy std threshold; optional Laplacian bump when
    ``EXODIA_INV_LAPLACE_MIN_VAR`` is set.
    """
    if cell_bgr is None or cell_bgr.size == 0:
        return False
    sig = extract_signals(cell_bgr)
    std_thresh = _env_float("EXODIA_INV_CELL_STD_THRESHOLD", 22.0)
    if sig.gray_std >= std_thresh:
        return True
    lap_min = _env_float("EXODIA_INV_LAPLACE_MIN_VAR", 300.0)
    if lap_min <= 0:
        return False
    from bot_eyes import _cell_laplacian_variance

    return _cell_laplacian_variance(cell_bgr) >= lap_min


def crop_inventory_slot_bgr(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    row: int,
    col: int,
    *,
    inset: Optional[int] = None,
) -> Optional[np.ndarray]:
    """Client-local BGR crop for one grid slot (full tile by default)."""
    if client_bgr is None or client_bgr.size == 0 or len(inventory_rect) != 4:
        return None
    rect = tuple(int(v) for v in inventory_rect[:4])
    inset_px = _item_match_inset_px(rect) if inset is None else max(0, int(inset))
    cell = inventory_grid_cell_xywh(rect, row, col, inset_px)
    if cell is None:
        return None
    x, y, w, h = cell
    h0, w0 = client_bgr.shape[:2]
    if x < 0 or y < 0 or x + w > w0 or y + h > h0:
        return None
    crop = client_bgr[y : y + h, x : x + w]
    return crop if crop.size else None


def _labels_imply_same_item(
    label_a: Optional[str],
    label_b: Optional[str],
) -> Optional[bool]:
    """``True``/``False`` when labels decide; ``None`` when vision must decide."""
    if label_a is None or label_b is None:
        return None
    if label_a == _UNKNOWN_LABEL or label_b == _UNKNOWN_LABEL:
        return None
    if label_a == label_b:
        return True
    id_a = seen_id_from_label(label_a)
    id_b = seen_id_from_label(label_b)
    if id_a and id_b:
        return id_a == id_b
    if not is_unknown_label(label_a) and not is_unknown_label(label_b):
        return False
    return None


def inventory_slot_crops_same_item(
    cell_a_bgr: np.ndarray,
    cell_b_bgr: np.ndarray,
    *,
    label_a: Optional[str] = None,
    label_b: Optional[str] = None,
    require_occupied: bool = True,
) -> SlotSameItemVerdict:
    """
    Compare two slot BGR crops — same item type, identity not required.

    When both ``label_*`` are known and agree (named stem or same ``unknown:<id>``),
    returns early. Otherwise uses ``signals_same_item`` (hue / edge / dHash / aspect).
    Stack counts may differ; empty slots are not items unless both are empty.
    """
    empty = {
        "color": 0.0,
        "edge": 0.0,
        "dhash": 0.0,
        "size": 0.0,
    }
    empty_scores = {"color": 1.0, "edge": 1.0, "dhash": 1.0, "size": 1.0}

    occ_a = inventory_slot_cell_looks_occupied(cell_a_bgr)
    occ_b = inventory_slot_cell_looks_occupied(cell_b_bgr)
    if require_occupied and (not occ_a or not occ_b):
        if not occ_a and not occ_b:
            return SlotSameItemVerdict(
                True,
                "both_empty",
                empty,
                empty_scores,
            )
        which = "a" if not occ_a else "b"
        return SlotSameItemVerdict(
            False,
            "slot_empty_%s" % which,
            empty,
            empty_scores,
        )

    label_verdict = _labels_imply_same_item(label_a, label_b)
    if label_verdict is True:
        return SlotSameItemVerdict(True, "labels_match", empty, empty_scores)
    if label_verdict is False:
        return SlotSameItemVerdict(False, "labels_differ", empty, empty_scores)

    sig_a = extract_signals(cell_a_bgr)
    sig_b = extract_signals(cell_b_bgr)
    same, distances, scores = signals_same_item(sig_a, sig_b)
    return SlotSameItemVerdict(
        same,
        "signals_match" if same else "signals_differ",
        distances,
        scores,
        signals_a=sig_a,
        signals_b=sig_b,
    )


def inventory_slots_same_item(
    client_bgr: np.ndarray,
    inventory_rect: Sequence[int],
    slot_a: Tuple[int, int],
    slot_b: Tuple[int, int],
    *,
    occupancy: Optional[Sequence[Sequence[bool]]] = None,
    slot_items: Optional[Sequence[Sequence[Optional[str]]]] = None,
    require_occupied: bool = True,
) -> SlotSameItemVerdict:
    """
    Compare grid slots ``(row, col)`` on a client frame.

    Pass ``occupancy`` / ``slot_items`` when already computed; otherwise occupancy
    is inferred per-crop and labels are omitted.
    """
    row_a, col_a = slot_a
    row_b, col_b = slot_b
    crop_a = crop_inventory_slot_bgr(client_bgr, inventory_rect, row_a, col_a)
    crop_b = crop_inventory_slot_bgr(client_bgr, inventory_rect, row_b, col_b)
    if crop_a is None or crop_b is None:
        return SlotSameItemVerdict(
            False,
            "crop_failed",
            {},
            {},
        )

    label_a: Optional[str] = None
    label_b: Optional[str] = None
    if occupancy is not None:
        if (
            row_a < len(occupancy)
            and col_a < len(occupancy[row_a])
            and not occupancy[row_a][col_a]
        ):
            label_a = None
        elif slot_items is not None:
            label_a = slot_items[row_a][col_a]
        else:
            label_a = _UNKNOWN_LABEL if inventory_slot_cell_looks_occupied(crop_a) else None

        if (
            row_b < len(occupancy)
            and col_b < len(occupancy[row_b])
            and not occupancy[row_b][col_b]
        ):
            label_b = None
        elif slot_items is not None:
            label_b = slot_items[row_b][col_b]
        else:
            label_b = _UNKNOWN_LABEL if inventory_slot_cell_looks_occupied(crop_b) else None
    elif slot_items is not None:
        if row_a < len(slot_items) and col_a < len(slot_items[row_a]):
            label_a = slot_items[row_a][col_a]
        if row_b < len(slot_items) and col_b < len(slot_items[row_b]):
            label_b = slot_items[row_b][col_b]

    return inventory_slot_crops_same_item(
        crop_a,
        crop_b,
        label_a=label_a,
        label_b=label_b,
        require_occupied=require_occupied,
    )


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
    frame_buckets: Optional[bool] = None,
) -> Tuple[
    Optional[List[List[Optional[str]]]],
    Dict[Tuple[int, int], float],
    Optional[Dict[Tuple[int, int], Dict[str, Any]]],
]:
    """
    Map occupied slots to item names from ``items/`` templates.

    Returns ``(grid_7x4, scores, diagnostics_or_None)`` where grid cells are:
    ``None`` = empty, ``unknown:<id>`` or ``"?"`` = occupied unknown, else named stem.

    With ``frame_buckets`` (or ``EXODIA_INV_FRAME_BUCKETS=1``), remaining ``?`` slots
    are grouped into ephemeral ``tmp:<8-hex>`` labels by fingerprint.
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

    use_buckets = (
        frame_buckets
        if frame_buckets is not None
        else _env_bool("EXODIA_INV_FRAME_BUCKETS", False)
    )
    if use_buckets:
        grid, _buckets = apply_frame_fingerprint_buckets(
            client_bgr, inventory_rect, occupancy, grid
        )

    diag_out = diagnostics if return_diagnostics else None
    return grid, scores, diag_out


def _overlay_label_text(label: str) -> str:
    if label.startswith("unknown:"):
        tid = seen_id_from_label(label) or label
        return tid if len(tid) <= 10 else tid[:8]
    tid = frame_bucket_id_from_label(label)
    if tid:
        return tid[:6]
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
            is_unk = (
                label == _UNKNOWN_LABEL
                or label.startswith("unknown:")
                or is_frame_bucket_label(label)
            )
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

    if occupancy is not None:
        vis = draw_inventory_bucket_counts_above(
            vis, inventory_rect, slot_items, occupancy
        )
    return vis


_NAME_SAFE_RE = re.compile(r"[^a-z0-9_]+")


def normalize_item_template_name(raw: str) -> Optional[str]:
    """
    Sanitize a user-provided template name for ``items/<name>.png``.

    Returns lowercase ``[a-z0-9_]`` stem, or ``None`` when invalid / temp-id-like.
    """
    if not raw or not str(raw).strip():
        return None
    name = str(raw).strip().lower().replace(" ", "_")
    name = _NAME_SAFE_RE.sub("", name)
    name = name.strip("_")
    if not name or is_temp_item_id(name):
        return None
    return name


def save_named_item_template(
    crop_bgr: np.ndarray,
    name: str,
    *,
    items_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    """
    Write a full slot BGR crop to ``items/<name>.png``.

    Raises ``ValueError`` for invalid names; ``FileExistsError`` when the file
    exists and ``overwrite`` is false.
    """
    stem = normalize_item_template_name(name)
    if stem is None:
        raise ValueError("invalid item template name: %r" % (name,))
    if crop_bgr is None or crop_bgr.size == 0:
        raise ValueError("empty slot crop")
    root = items_dir if items_dir is not None else items_directory()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("%s.png" % stem)
    if path.is_file() and not overwrite:
        raise FileExistsError(str(path))
    out_bgr = _strip_runelite_tags_bgr(crop_bgr)
    if not cv2.imwrite(str(path), out_bgr):
        raise RuntimeError("failed to write %s" % path)
    return path


def bucket_slots_for_label(
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Sequence[Sequence[bool]],
    label: str,
) -> List[Tuple[int, int]]:
    """Occupied grid coords sharing ``label`` (named, ``tmp:``, ``unknown:``, or ``?``)."""
    out: List[Tuple[int, int]] = []
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if row >= len(occupancy) or col >= len(occupancy[row]) or not occupancy[row][col]:
                continue
            if row >= len(slot_items) or col >= len(slot_items[row]):
                continue
            if slot_items[row][col] == label:
                out.append((row, col))
    return out


def slot_at_client_point(
    client_x: int,
    client_y: int,
    inventory_rect: Sequence[int],
    *,
    occupancy: Optional[Sequence[Sequence[bool]]] = None,
) -> Optional[Tuple[int, int]]:
    """Hit-test client-local ``(x, y)`` → ``(row, col)`` or ``None``."""
    if len(inventory_rect) != 4:
        return None
    rect = tuple(int(v) for v in inventory_rect[:4])
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if occupancy is not None:
                if (
                    row >= len(occupancy)
                    or col >= len(occupancy[row])
                    or not occupancy[row][col]
                ):
                    continue
            cell = inventory_grid_cell_xywh(rect, row, col, 0)
            if cell is None:
                continue
            x, y, w, h = cell
            if x <= client_x < x + w and y <= client_y < y + h:
                return row, col
    return None


def count_labeled_item_slots(
    slot_items: Sequence[Sequence[Optional[str]]],
    occupancy: Sequence[Sequence[bool]],
    item_name: str,
) -> int:
    """Occupied slots whose identify label matches ``item_name`` (case-insensitive)."""
    needle = item_name.strip().lower()
    if not needle:
        return 0
    n = 0
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            if row >= len(occupancy) or col >= len(occupancy[row]) or not occupancy[row][col]:
                continue
            if row >= len(slot_items) or col >= len(slot_items[row]):
                continue
            label = slot_items[row][col]
            if label and label.strip().lower() == needle:
                n += 1
    return n


def read_inventory_labels(eyes) -> Tuple[
    Sequence[Sequence[Optional[str]]], Sequence[Sequence[bool]]
]:
    """Identify occupied inventory slots (``frame_buckets=True``) after ``bot_update``."""
    pe = eyes.perception_envelope or {}
    occ = pe.get("inventory_slot_occupancy")
    if occ is None:
        occ = eyes.compute_inventory_slot_occupancy()
    grid, _, _ = identify_inventory_slot_items(
        eyes.curr_client,
        eyes.inventory_rect,
        occ,
        frame_buckets=True,
    )
    return grid, occ
