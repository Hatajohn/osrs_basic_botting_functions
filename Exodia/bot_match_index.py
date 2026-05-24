"""
Gated template matching with multi-signal diagnostics and seen-item fingerprint registry.

Named templates live in ``items/flax.png``; auto-generated unknowns use 8-char hex
stems under ``items/seen/<id>.png`` with ``items/fingerprints/<id>.json`` sidecars.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from bot_inventory_count import (
    _read_stack_quantity,
    _slot_gray_for_match,
    _slot_template_score,
    _stack_band_rect,
    _stack_digit_roi,
)

_EXODIA_DIR = Path(__file__).resolve().parent
_TEMP_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_HUE_BINS = 16
_EDGE_SIZE = 16
_DEFAULT_SLOT_W = 50
_DEFAULT_SLOT_H = 45
_SLOT_PLATE_BGR = (52, 42, 32)  # typical OSRS inventory plate
_UNKNOWN_PREFIX = "unknown:"

__all__ = [
    "MatchSignals",
    "RejectionReason",
    "CandidateResult",
    "MatchVerdict",
    "TemplateEntry",
    "TemplateCatalog",
    "SeenItemEntry",
    "SeenItemRegistry",
    "DuplicateCluster",
    "CleanupReport",
    "is_temp_item_id",
    "allocate_temp_id",
    "seen_label",
    "seen_id_from_label",
    "is_unknown_label",
    "extract_signals",
    "items_directory",
    "seen_images_directory",
    "seen_fingerprints_directory",
    "load_named_catalog",
    "load_seen_registry",
    "audit_seen_duplicates",
    "merge_duplicate_clusters",
]


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
    return (_EXODIA_DIR / "items").resolve()


def _items_subdir(env_key: str, default_name: str, items_root: Optional[Path] = None) -> Path:
    root = items_root if items_root is not None else items_directory()
    raw = os.environ.get(env_key, "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (root / p).resolve()
    return (root / default_name).resolve()


def seen_images_directory(items_root: Optional[Path] = None) -> Path:
    """Temp-id slot PNG crops (default ``items/seen/``)."""
    return _items_subdir("EXODIA_SEEN_ITEMS_DIR", "seen", items_root)


def seen_fingerprints_directory(items_root: Optional[Path] = None) -> Path:
    """Temp-id JSON sidecars (default ``items/fingerprints/``)."""
    return _items_subdir("EXODIA_SEEN_FINGERPRINTS_DIR", "fingerprints", items_root)


def is_temp_item_id(stem: str) -> bool:
    s = stem.strip().lower()
    return bool(_TEMP_ID_RE.match(s))


def allocate_temp_id(existing_stems: Iterable[str]) -> str:
    taken = {s.strip().lower() for s in existing_stems}
    for _ in range(256):
        candidate = secrets.token_hex(4)
        if candidate not in taken:
            return candidate
    raise RuntimeError("could not allocate unique 8-char temp item id")


def seen_label(temp_id: str) -> str:
    return _UNKNOWN_PREFIX + temp_id.strip().lower()


def seen_item_display_label(temp_id: str, name: Optional[str] = None) -> str:
    """Human label for a seen fingerprint — ``name`` when set, else ``unknown:<id>``."""
    if name and str(name).strip():
        return str(name).strip()
    return seen_label(temp_id)


def seen_id_from_label(label: str) -> Optional[str]:
    if not label or not label.startswith(_UNKNOWN_PREFIX):
        return None
    tid = label[len(_UNKNOWN_PREFIX) :].strip().lower()
    return tid if is_temp_item_id(tid) else None


def is_unknown_label(label: Optional[str]) -> bool:
    if label in (None, "?"):
        return True
    return seen_id_from_label(label) is not None


def _embed_icon_in_slot_canvas(bgr: np.ndarray) -> np.ndarray:
    """
    Center a standalone icon PNG on a full slot-sized plate so gate signals
    compare like live inventory crops (``items/flax.png`` is icon-only).
    """
    if bgr is None or bgr.size == 0:
        return bgr
    h, w = bgr.shape[:2]
    if h >= _DEFAULT_SLOT_H - 2 and w >= _DEFAULT_SLOT_W - 2:
        return bgr
    canvas = np.zeros((_DEFAULT_SLOT_H, _DEFAULT_SLOT_W, 3), dtype=np.uint8)
    canvas[:] = _SLOT_PLATE_BGR
    scale = min(
        (_DEFAULT_SLOT_W - 4) / max(w, 1),
        (_DEFAULT_SLOT_H - 4) / max(h, 1),
        1.0,
    )
    if scale < 1.0:
        bgr = cv2.resize(bgr, (max(1, int(w * scale)), max(1, int(h * scale))))
        h, w = bgr.shape[:2]
    y0 = (_DEFAULT_SLOT_H - h) // 2
    x0 = (_DEFAULT_SLOT_W - w) // 2
    canvas[y0 : y0 + h, x0 : x0 + w] = bgr
    return canvas


def _dhash(gray: np.ndarray) -> int:
    if gray is None or gray.size == 0:
        return 0
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = 0
    for i, v in enumerate(diff.flatten()):
        if v:
            bits |= 1 << i
    return int(bits)


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _detect_stack_text(cell_bgr: np.ndarray) -> Tuple[bool, int]:
    if cell_bgr is None or cell_bgr.size == 0:
        return False, 0
    roi = _stack_digit_roi(cell_bgr)
    if roi.size == 0:
        return False, 0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (18, 80, 120), (40, 255, 255))
    yellow_px = int(cv2.countNonZero(yellow))
    white_px = 0
    if _env_bool("EXODIA_STACK_WHITE_TEXT", True):
        white = cv2.inRange(hsv, (0, 0, 180), (180, 60, 255))
        white_px = int(cv2.countNonZero(white))
    present = yellow_px >= 8 or white_px >= 8
    qty = _read_stack_quantity(cell_bgr) if present else 0
    return present, qty


def _icon_body_mask(cell_bgr: np.ndarray) -> np.ndarray:
    h, w = cell_bgr.shape[:2]
    y1, x1 = _stack_band_rect(h, w)
    mask = np.ones((h, w), dtype=np.uint8)
    mask[0:y1, 0:x1] = 0
    return mask


def _hue_histogram(cell_bgr: np.ndarray, body_mask: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.float32)
    sat = hsv[:, :, 1]
    valid = (body_mask > 0) & (sat >= 25)
    hist = np.zeros(_HUE_BINS, dtype=np.float32)
    if not np.any(valid):
        return hist
    vals = hue[valid]
    bins = np.clip((vals / 180.0 * _HUE_BINS).astype(np.int32), 0, _HUE_BINS - 1)
    for b in bins:
        hist[b] += 1.0
    total = float(hist.sum())
    if total > 0:
        hist /= total
    return hist


def _edge_bitmap(gray: np.ndarray) -> np.ndarray:
    edges = cv2.Canny(gray, 40, 120)
    small = cv2.resize(edges, (_EDGE_SIZE, _EDGE_SIZE), interpolation=cv2.INTER_AREA)
    return (small.astype(np.float32) / 255.0).flatten()


def _icon_aspect(cell_bgr: np.ndarray, body_mask: np.ndarray) -> float:
    hsv = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    icon = (body_mask > 0) & (sat >= 30)
    if not np.any(icon):
        return 1.0
    ys, xs = np.where(icon)
    bh = max(1, int(ys.max()) - int(ys.min()) + 1)
    bw = max(1, int(xs.max()) - int(xs.min()) + 1)
    return float(bw) / float(bh)


@dataclass
class MatchSignals:
    hue_hist: np.ndarray
    edge_vec: np.ndarray
    dhash: int
    aspect: float
    gray_mean: float
    gray_std: float
    stack_text_present: bool = False
    stack_qty: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "aspect": self.aspect,
            "dhash": self.dhash,
            "gray_mean": self.gray_mean,
            "gray_std": self.gray_std,
            "stack_text_present": self.stack_text_present,
            "stack_qty": self.stack_qty,
        }


def extract_signals(cell_bgr: np.ndarray) -> MatchSignals:
    if cell_bgr is None or cell_bgr.size == 0:
        z = np.zeros(_HUE_BINS, dtype=np.float32)
        return MatchSignals(
            hue_hist=z,
            edge_vec=np.zeros(_EDGE_SIZE * _EDGE_SIZE, dtype=np.float32),
            dhash=0,
            aspect=1.0,
            gray_mean=0.0,
            gray_std=0.0,
        )
    gray = _slot_gray_for_match(cell_bgr)
    body = _icon_body_mask(cell_bgr)
    stack_present, stack_qty = _detect_stack_text(cell_bgr)
    body_vals = gray[body > 0]
    g_mean = float(np.mean(body_vals)) if body_vals.size else float(np.mean(gray))
    g_std = float(np.std(body_vals)) if body_vals.size else float(np.std(gray))
    return MatchSignals(
        hue_hist=_hue_histogram(cell_bgr, body),
        edge_vec=_edge_bitmap(gray),
        dhash=_dhash(gray),
        aspect=_icon_aspect(cell_bgr, body),
        gray_mean=g_mean,
        gray_std=g_std,
        stack_text_present=stack_present,
        stack_qty=int(stack_qty),
    )


@dataclass(frozen=True)
class RejectionReason:
    kind: str
    distance: float
    threshold: float


@dataclass
class CandidateResult:
    name: str
    gate_passed: bool
    rejections: Tuple[RejectionReason, ...] = ()
    signal_scores: Dict[str, float] = field(default_factory=dict)
    template_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "gate_passed": self.gate_passed,
            "rejections": [
                {"kind": r.kind, "distance": r.distance, "threshold": r.threshold}
                for r in self.rejections
            ],
            "signal_scores": dict(self.signal_scores),
            "template_score": self.template_score,
        }


@dataclass
class MatchVerdict:
    accepted: bool
    best_name: Optional[str]
    best_score: float
    threshold: float
    candidates: Tuple[CandidateResult, ...]
    skipped_count: int
    query_signals: Optional[MatchSignals] = None
    created: bool = False

    def rejection_summary(self) -> str:
        if not self.candidates:
            return ""
        best = max(self.candidates, key=lambda c: c.template_score if c.gate_passed else -1.0)
        if best.gate_passed:
            return ""
        kinds = sorted({r.kind for r in best.rejections})
        return ",".join(kinds)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "accepted": self.accepted,
            "best_name": self.best_name,
            "best_score": self.best_score,
            "threshold": self.threshold,
            "skipped_by_gates": self.skipped_count,
            "created": self.created,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.query_signals is not None:
            out["query_signals"] = self.query_signals.to_dict()
        return out


def _hist_l1(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sum(np.abs(a - b)))


def _edge_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


def gate_signals(
    entry_sig: MatchSignals,
    query_sig: MatchSignals,
    *,
    entry_aspect: float = 1.0,
) -> Tuple[Tuple[RejectionReason, ...], Dict[str, float]]:
    color_thr = _env_float("EXODIA_MATCH_COLOR_MAX_L1", 0.45)
    edge_thr = _env_float("EXODIA_MATCH_EDGE_MAX_DIFF", 0.35)
    size_thr = _env_float("EXODIA_MATCH_SIZE_MAX_RATIO", 0.35)
    dhash_thr = _env_int("EXODIA_MATCH_DHASH_MAX_BITS", 12)

    color_dist = _hist_l1(entry_sig.hue_hist, query_sig.hue_hist)
    edge_dist = _edge_diff(entry_sig.edge_vec, query_sig.edge_vec)
    dhash_dist = float(_hamming(entry_sig.dhash, query_sig.dhash))
    aspect_delta = abs(entry_aspect - query_sig.aspect) / max(entry_aspect, query_sig.aspect, 1e-6)

    scores = {
        "color": max(0.0, 1.0 - color_dist / max(color_thr, 1e-6)),
        "edge": max(0.0, 1.0 - edge_dist / max(edge_thr, 1e-6)),
        "dhash": max(0.0, 1.0 - dhash_dist / max(float(dhash_thr), 1.0)),
    }

    rejections: List[RejectionReason] = []
    if color_dist > color_thr:
        rejections.append(RejectionReason("color", color_dist, color_thr))
    if edge_dist > edge_thr:
        rejections.append(RejectionReason("edge", edge_dist, edge_thr))
    if aspect_delta > size_thr:
        rejections.append(RejectionReason("size", aspect_delta, size_thr))
    if dhash_dist > float(dhash_thr):
        rejections.append(RejectionReason("dhash", dhash_dist, float(dhash_thr)))
    return tuple(rejections), scores


@dataclass
class TemplateEntry:
    name: str
    template_gray: np.ndarray
    template_bgr: Optional[np.ndarray]
    signals: MatchSignals
    aspect: float


class TemplateCatalog:
    """Named ``items/*.png`` templates (stems that are not 8-char hex ids)."""

    def __init__(self, entries: Sequence[TemplateEntry]) -> None:
        self._entries = list(entries)
        self._by_name = {e.name: e for e in entries}

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(e.name for e in self._entries)

    def iter_candidates(
        self,
        query_sig: MatchSignals,
        priority_names: Sequence[str] = (),
    ) -> List[TemplateEntry]:
        priority = [n.strip().lower() for n in priority_names if n.strip()]
        ordered: List[TemplateEntry] = []
        seen = set()
        for name in priority:
            ent = self._by_name.get(name)
            if ent is not None and name not in seen:
                ordered.append(ent)
                seen.add(name)
        for ent in self._entries:
            if ent.name not in seen:
                ordered.append(ent)
                seen.add(ent.name)
        return ordered

    def match_query(
        self,
        query_bgr: np.ndarray,
        *,
        threshold: Optional[float] = None,
        priority_names: Sequence[str] = (),
        strict_gates: bool = False,
    ) -> MatchVerdict:
        thr = threshold if threshold is not None else _env_float(
            "EXODIA_INV_ITEM_MATCH_THRESHOLD", 0.40
        )
        sig_q = extract_signals(query_bgr)
        candidates: List[CandidateResult] = []
        skipped = 0
        best_name: Optional[str] = None
        best_score = 0.0

        for entry in self.iter_candidates(sig_q, priority_names):
            rejections, sig_scores = gate_signals(entry.signals, sig_q, entry_aspect=entry.aspect)
            if rejections:
                skipped += 1
                candidates.append(
                    CandidateResult(
                        name=entry.name,
                        gate_passed=False,
                        rejections=rejections,
                        signal_scores=sig_scores,
                    )
                )
                continue
            score = _slot_template_score(query_bgr, entry.template_gray)
            candidates.append(
                CandidateResult(
                    name=entry.name,
                    gate_passed=True,
                    signal_scores=sig_scores,
                    template_score=score,
                )
            )
            if score > best_score:
                best_score = score
                best_name = entry.name

        if not strict_gates and best_score <= 0.0 and candidates:
            for entry in self.iter_candidates(sig_q, priority_names):
                score = _slot_template_score(query_bgr, entry.template_gray)
                for i, cand in enumerate(candidates):
                    if cand.name == entry.name:
                        candidates[i] = CandidateResult(
                            name=entry.name,
                            gate_passed=score > 0.0,
                            rejections=cand.rejections,
                            signal_scores=cand.signal_scores,
                            template_score=score,
                        )
                        break
                if score > best_score:
                    best_score = score
                    best_name = entry.name

        accepted = best_name is not None and best_score >= thr
        return MatchVerdict(
            accepted=accepted,
            best_name=best_name if accepted else best_name,
            best_score=best_score,
            threshold=thr,
            candidates=tuple(candidates),
            skipped_count=skipped,
            query_signals=sig_q,
        )


@dataclass
class SeenItemEntry:
    temp_id: str
    template_gray: np.ndarray
    template_bgr: np.ndarray
    signals: MatchSignals
    aspect: float
    first_seen_ts: float
    sightings: int = 1
    name: Optional[str] = None

    def display_label(self) -> str:
        return seen_item_display_label(self.temp_id, self.name)


class SeenItemRegistry:
    """Temp-id fingerprints: ``items/seen/<8-hex>.png`` + ``items/fingerprints/<8-hex>.json``."""

    def __init__(
        self,
        items_dir: Path,
        *,
        images_dir: Optional[Path] = None,
        fingerprints_dir: Optional[Path] = None,
        entries: Optional[List[SeenItemEntry]] = None,
    ) -> None:
        self.items_dir = items_dir
        self.images_dir = images_dir if images_dir is not None else seen_images_directory(items_dir)
        self.fingerprints_dir = (
            fingerprints_dir
            if fingerprints_dir is not None
            else seen_fingerprints_directory(items_dir)
        )
        self._entries: Dict[str, SeenItemEntry] = {}
        if entries:
            for e in entries:
                self._entries[e.temp_id] = e

    def _png_path(self, temp_id: str) -> Path:
        return self.images_dir / (temp_id + ".png")

    def _json_path(self, temp_id: str) -> Path:
        return self.fingerprints_dir / (temp_id + ".json")

    def _legacy_png_path(self, temp_id: str) -> Path:
        return self.items_dir / (temp_id + ".png")

    def _legacy_json_path(self, temp_id: str) -> Path:
        return self.items_dir / (temp_id + ".json")

    def _resolve_png_path(self, temp_id: str) -> Optional[Path]:
        path = self._png_path(temp_id)
        if path.is_file():
            return path
        legacy = self._legacy_png_path(temp_id)
        return legacy if legacy.is_file() else None

    def _resolve_json_path(self, temp_id: str) -> Optional[Path]:
        path = self._json_path(temp_id)
        if path.is_file():
            return path
        legacy = self._legacy_json_path(temp_id)
        return legacy if legacy.is_file() else None

    def _relocate_legacy_temp_files(self, temp_id: str) -> None:
        """Move legacy ``items/<id>.{png,json}`` into seen/ + fingerprints/."""
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.fingerprints_dir.mkdir(parents=True, exist_ok=True)
        leg_png = self._legacy_png_path(temp_id)
        leg_json = self._legacy_json_path(temp_id)
        new_png = self._png_path(temp_id)
        new_json = self._json_path(temp_id)
        if leg_png.is_file() and not new_png.is_file():
            leg_png.replace(new_png)
        if leg_json.is_file() and not new_json.is_file():
            leg_json.replace(new_json)

    def _unlink_temp_files(self, temp_id: str) -> None:
        for path in (
            self._png_path(temp_id),
            self._json_path(temp_id),
            self._legacy_png_path(temp_id),
            self._legacy_json_path(temp_id),
        ):
            if path.is_file():
                path.unlink(missing_ok=True)

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(self._entries.keys())

    def _existing_stems(self) -> set:
        stems = set(self._entries.keys())
        for directory in (self.images_dir, self.items_dir):
            if not directory.is_dir():
                continue
            for p in directory.glob("*.png"):
                stem = p.stem.lower()
                if is_temp_item_id(stem):
                    stems.add(stem)
        return stems

    def label_for(self, temp_id: str) -> str:
        entry = self._entries.get(temp_id.strip().lower())
        if entry is not None:
            return entry.display_label()
        return seen_label(temp_id)

    def _write_sidecar(self, entry: SeenItemEntry, *, extra: Optional[Dict[str, Any]] = None) -> None:
        self.fingerprints_dir.mkdir(parents=True, exist_ok=True)
        path = self._json_path(entry.temp_id)
        payload: Dict[str, Any] = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = {}
        payload.update(
            {
                "id": entry.temp_id,
                "first_seen_ts": entry.first_seen_ts,
                "sightings": entry.sightings,
            }
        )
        if entry.name and str(entry.name).strip():
            payload["name"] = str(entry.name).strip()
        if extra:
            payload.update(extra)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _increment_sidecar(self, temp_id: str) -> None:
        entry = self._entries[temp_id]
        entry.sightings += 1
        self._write_sidecar(entry)

    def fast_match_id(self, query_bgr: np.ndarray, sig_q: MatchSignals) -> Optional[str]:
        dhash_thr = _env_int("EXODIA_SEEN_DHASH_MAX_BITS", 10)
        color_thr = _env_float("EXODIA_SEEN_COLOR_MAX_L1", 0.40)
        best_id: Optional[str] = None
        best_d = dhash_thr + 1
        for entry in self._entries.values():
            d = _hamming(sig_q.dhash, entry.signals.dhash)
            if d > dhash_thr:
                continue
            color_dist = _hist_l1(entry.signals.hue_hist, sig_q.hue_hist)
            if color_dist > color_thr:
                continue
            if d < best_d:
                best_d = d
                best_id = entry.temp_id
        return best_id

    def match_query(
        self,
        query_bgr: np.ndarray,
        *,
        threshold: Optional[float] = None,
    ) -> MatchVerdict:
        thr = threshold if threshold is not None else _env_float("EXODIA_SEEN_MATCH_THRESHOLD", 0.40)
        sig_q = extract_signals(query_bgr)
        fast_id = self.fast_match_id(query_bgr, sig_q)
        if fast_id is not None:
            entry = self._entries[fast_id]
            rejections, _sig_scores = gate_signals(
                entry.signals, sig_q, entry_aspect=entry.aspect
            )
            score = _slot_template_score(query_bgr, entry.template_gray)
            if not rejections and score >= thr:
                return MatchVerdict(
                    accepted=True,
                    best_name=fast_id,
                    best_score=score,
                    threshold=thr,
                    candidates=(),
                    skipped_count=0,
                    query_signals=sig_q,
                )

        catalog_entries = [
            TemplateEntry(
                name=e.temp_id,
                template_gray=e.template_gray,
                template_bgr=e.template_bgr,
                signals=e.signals,
                aspect=e.aspect,
            )
            for e in self._entries.values()
        ]
        cat = TemplateCatalog(catalog_entries)
        verdict = cat.match_query(query_bgr, threshold=thr, strict_gates=True)
        if verdict.accepted and verdict.best_name:
            verdict.best_name = verdict.best_name
        return verdict

    def resolve(
        self,
        query_bgr: np.ndarray,
        *,
        threshold: Optional[float] = None,
    ) -> Tuple[Optional[str], MatchVerdict, bool]:
        """
        Returns ``(label, verdict, created)`` where label is ``unknown:<id>`` or ``None``.
        """
        if not _env_bool("EXODIA_SEEN_ITEMS", False):
            empty = MatchVerdict(False, None, 0.0, 0.0, (), 0)
            return None, empty, False

        verdict = self.match_query(query_bgr, threshold=threshold)
        if verdict.accepted and verdict.best_name:
            tid = verdict.best_name
            self._increment_sidecar(tid)
            return self.label_for(tid), verdict, False

        sig_q = extract_signals(query_bgr)
        tid, created = self.register(query_bgr, sig_q=sig_q, verdict=verdict)
        return self.label_for(tid), verdict, created

    def register(
        self,
        query_bgr: np.ndarray,
        *,
        sig_q: Optional[MatchSignals] = None,
        verdict: Optional[MatchVerdict] = None,
    ) -> Tuple[str, bool]:
        sig = sig_q if sig_q is not None else extract_signals(query_bgr)
        retry = self.match_query(query_bgr)
        if retry.accepted and retry.best_name:
            self._increment_sidecar(retry.best_name)
            return retry.best_name, False

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.fingerprints_dir.mkdir(parents=True, exist_ok=True)
        temp_id = allocate_temp_id(self._existing_stems())
        gray = _slot_gray_for_match(query_bgr)
        png_path = self._png_path(temp_id)
        cv2.imwrite(str(png_path), query_bgr)
        now = time.time()
        entry = SeenItemEntry(
            temp_id=temp_id,
            template_gray=gray,
            template_bgr=query_bgr.copy(),
            signals=sig,
            aspect=sig.aspect,
            first_seen_ts=now,
            sightings=1,
        )
        self._entries[temp_id] = entry
        extra: Dict[str, Any] = {}
        if verdict is not None:
            extra["first_verdict"] = verdict.to_dict()
        self._write_sidecar(entry, extra=extra)
        return temp_id, True

    @classmethod
    def load_from_disk(cls, items_dir: Optional[Path] = None) -> "SeenItemRegistry":
        root = items_dir if items_dir is not None else items_directory()
        images_dir = seen_images_directory(root)
        fingerprints_dir = seen_fingerprints_directory(root)
        reg = cls(root, images_dir=images_dir, fingerprints_dir=fingerprints_dir)

        def _ingest(path: Path) -> None:
            stem = path.stem.lower()
            if not is_temp_item_id(stem) or stem in reg._entries:
                return
            bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if bgr is None or bgr.size == 0:
                return
            meta_path = reg._resolve_json_path(stem)
            first_ts = path.stat().st_mtime
            sightings = 1
            display_name: Optional[str] = None
            if meta_path is not None and meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    first_ts = float(meta.get("first_seen_ts", first_ts))
                    sightings = int(meta.get("sightings", 1))
                    raw_name = meta.get("name")
                    if raw_name is not None and str(raw_name).strip():
                        display_name = str(raw_name).strip()
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            sig = extract_signals(bgr)
            reg._entries[stem] = SeenItemEntry(
                temp_id=stem,
                template_gray=_slot_gray_for_match(bgr),
                template_bgr=bgr,
                signals=sig,
                aspect=sig.aspect,
                first_seen_ts=first_ts,
                sightings=sightings,
                name=display_name,
            )
            reg._relocate_legacy_temp_files(stem)

        if images_dir.is_dir():
            for path in sorted(images_dir.glob("*.png")):
                _ingest(path)
        if root.is_dir():
            for path in sorted(root.glob("*.png")):
                _ingest(path)

        if _env_bool("EXODIA_SEEN_MERGE_ON_LOAD", True):
            reg._merge_duplicates_on_load()
        return reg

    def _merge_duplicates_on_load(self) -> None:
        ids = list(self._entries.keys())
        thr = _env_float("EXODIA_SEEN_MATCH_THRESHOLD", 0.40)
        dhash_thr = _env_int("EXODIA_SEEN_DHASH_MAX_BITS", 10)
        color_thr = _env_float("EXODIA_SEEN_COLOR_MAX_L1", 0.40)
        parent: Dict[str, str] = {i: i for i in ids}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            ea, eb = self._entries[ra], self._entries[rb]
            keep, drop = (ra, rb) if ea.first_seen_ts <= eb.first_seen_ts else (rb, ra)
            parent[find(drop)] = find(keep)
            self._entries[keep].sightings += self._entries[drop].sightings

        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                ea, eb = self._entries[a], self._entries[b]
                if _hamming(ea.signals.dhash, eb.signals.dhash) > dhash_thr:
                    continue
                if _hist_l1(ea.signals.hue_hist, eb.signals.hue_hist) > color_thr:
                    continue
                s1 = _slot_template_score(ea.template_bgr, eb.template_gray)
                s2 = _slot_template_score(eb.template_bgr, ea.template_gray)
                if min(s1, s2) >= thr:
                    union(a, b)

        clusters: Dict[str, List[str]] = {}
        for i in ids:
            clusters.setdefault(find(i), []).append(i)

        for canonical, members in clusters.items():
            if len(members) < 2:
                continue
            for drop in members:
                if drop == canonical:
                    continue
                self._unlink_temp_files(drop)
                self._entries.pop(drop, None)
            self._write_sidecar(self._entries[canonical])


def _load_png_entry(path: Path) -> Optional[Tuple[str, np.ndarray, np.ndarray, MatchSignals]]:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None
    stem = path.stem.lower()
    signal_bgr = bgr if is_temp_item_id(stem) else _embed_icon_in_slot_canvas(bgr)
    sig = extract_signals(signal_bgr)
    gray = _slot_gray_for_match(bgr)
    return stem, bgr, gray, sig


def load_named_catalog(items_dir: Optional[Path] = None) -> TemplateCatalog:
    root = items_dir if items_dir is not None else items_directory()
    entries: List[TemplateEntry] = []
    if not root.is_dir():
        return TemplateCatalog(entries)
    for path in sorted(root.glob("*.png")):
        stem = path.stem.lower()
        if is_temp_item_id(stem):
            continue
        loaded = _load_png_entry(path)
        if loaded is None:
            continue
        _, bgr, gray, sig = loaded
        entries.append(
            TemplateEntry(
                name=stem,
                template_gray=gray,
                template_bgr=bgr,
                signals=sig,
                aspect=sig.aspect,
            )
        )
    return TemplateCatalog(entries)


def load_seen_registry(items_dir: Optional[Path] = None) -> SeenItemRegistry:
    return SeenItemRegistry.load_from_disk(items_dir)


@dataclass(frozen=True)
class DuplicateCluster:
    canonical_id: str
    member_ids: Tuple[str, ...]
    pairwise_scores: Dict[Tuple[str, str], float]
    match_kind: str
    review: bool = False


@dataclass
class CleanupReport:
    clusters: Tuple[DuplicateCluster, ...]
    orphan_files: Tuple[str, ...]
    already_labeled: Tuple[Tuple[str, str], ...]
    dry_run: bool
    merged_count: int = 0

    def to_text(self) -> str:
        lines = ["cleanup dry_run=%s merged=%d" % (self.dry_run, self.merged_count)]
        for c in self.clusters:
            flag = " REVIEW" if c.review else ""
            lines.append(
                "cluster canonical=%s members=%s kind=%s%s"
                % (c.canonical_id, list(c.member_ids), c.match_kind, flag)
            )
        for o in self.orphan_files:
            lines.append("orphan: %s" % o)
        for temp_id, known in self.already_labeled:
            lines.append("already_labeled: temp=%s named=%s" % (temp_id, known))
        return "\n".join(lines)


def audit_seen_duplicates(
    *,
    items_dir: Optional[Path] = None,
    extra_dirs: Sequence[Union[str, Path]] = (),
) -> CleanupReport:
    root = items_dir if items_dir is not None else items_directory()
    images_dir = seen_images_directory(root)
    fingerprints_dir = seen_fingerprints_directory(root)
    match_thr = _env_float("EXODIA_CLEANUP_MATCH_THRESHOLD", 0.38)
    dhash_thr = _env_int("EXODIA_CLEANUP_DHASH_MAX_BITS", 8)
    review_low = _env_float("EXODIA_CLEANUP_REVIEW_LOW", 0.32)

    named: Dict[str, Tuple[np.ndarray, np.ndarray, MatchSignals]] = {}
    temp: Dict[str, Tuple[np.ndarray, np.ndarray, MatchSignals]] = {}
    orphan: List[str] = []
    already: List[Tuple[str, str]] = []

    if root.is_dir():
        for path in sorted(root.glob("*.png")):
            loaded = _load_png_entry(path)
            if loaded is None:
                continue
            stem, bgr, gray, sig = loaded
            if is_temp_item_id(stem):
                continue
            named[stem] = (bgr, gray, sig)

    temp_sources: List[Path] = []
    if images_dir.is_dir():
        temp_sources.extend(sorted(images_dir.glob("*.png")))
    if root.is_dir():
        temp_sources.extend(sorted(root.glob("*.png")))

    seen_stems: set = set()
    for path in temp_sources:
        loaded = _load_png_entry(path)
        if loaded is None:
            continue
        stem, bgr, gray, sig = loaded
        if not is_temp_item_id(stem) or stem in seen_stems:
            continue
        seen_stems.add(stem)
        temp[stem] = (bgr, gray, sig)
        json_path = fingerprints_dir / (stem + ".json")
        legacy_json = root / (stem + ".json")
        if not json_path.is_file() and not legacy_json.is_file():
            orphan.append(str(path))

    for temp_id, (tbgr, tgray, tsig) in temp.items():
        for nname, (nbgr, ngray, _) in named.items():
            s1 = _slot_template_score(tbgr, ngray)
            s2 = _slot_template_score(nbgr, tgray)
            if max(s1, s2) >= match_thr:
                already.append((temp_id, nname))

    ids = sorted(temp.keys())
    parent: Dict[str, str] = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(b)] = find(a)

    pair_scores: Dict[Tuple[str, str], float] = {}
    pair_kind: Dict[Tuple[str, str], str] = {}

    for i, a in enumerate(ids):
        _, _, asig = temp[a]
        for b in ids[i + 1 :]:
            _, _, bsig = temp[b]
            d_ok = _hamming(asig.dhash, bsig.dhash) <= dhash_thr
            tbgr, tgray, _ = temp[a]
            bbgr, bgray, _ = temp[b]
            s1 = _slot_template_score(tbgr, bgray)
            s2 = _slot_template_score(bbgr, tgray)
            score = min(s1, s2)
            pair_scores[(a, b)] = score
            pair_scores[(b, a)] = score
            if d_ok and score >= match_thr:
                union(a, b)
                pair_kind[(a, b)] = "both"
            elif d_ok:
                pair_kind[(a, b)] = "dhash"
            elif score >= match_thr:
                pair_kind[(a, b)] = "full"

    grouped: Dict[str, List[str]] = {}
    for i in ids:
        grouped.setdefault(find(i), []).append(i)

    clusters: List[DuplicateCluster] = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        members = tuple(sorted(set(members)))
        scores_in_cluster: Dict[Tuple[str, str], float] = {}
        kinds = set()
        review = False
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                sc = pair_scores.get((a, b), 0.0)
                scores_in_cluster[(a, b)] = sc
                kinds.add(pair_kind.get((a, b), "full"))
                if review_low <= sc < match_thr:
                    review = True
        canonical = min(
            members,
            key=lambda m: (
                fingerprints_dir / (m + ".json")
            ).stat().st_mtime
            if (fingerprints_dir / (m + ".json")).is_file()
            else (
                (root / (m + ".json")).stat().st_mtime
                if (root / (m + ".json")).is_file()
                else 1e18
            ),
        )
        clusters.append(
            DuplicateCluster(
                canonical_id=canonical,
                member_ids=members,
                pairwise_scores=scores_in_cluster,
                match_kind="+".join(sorted(kinds)) if kinds else "full",
                review=review,
            )
        )

    return CleanupReport(
        clusters=tuple(clusters),
        orphan_files=tuple(orphan),
        already_labeled=tuple(already),
        dry_run=True,
        merged_count=0,
    )


def merge_duplicate_clusters(
    report: CleanupReport,
    *,
    items_dir: Optional[Path] = None,
) -> CleanupReport:
    root = items_dir if items_dir is not None else items_directory()
    images_dir = seen_images_directory(root)
    fingerprints_dir = seen_fingerprints_directory(root)
    merged = 0
    log_path = root / ".cleanup.log"
    auto = _env_bool("EXODIA_CLEANUP_AUTO_MERGE", False)

    def _unlink_temp(temp_id: str) -> None:
        for path in (
            images_dir / (temp_id + ".png"),
            fingerprints_dir / (temp_id + ".json"),
            root / (temp_id + ".png"),
            root / (temp_id + ".json"),
        ):
            if not path.is_file():
                continue
            if path.suffix == ".json":
                try:
                    meta = json.loads(path.read_text(encoding="utf-8"))
                    meta["merged_into"] = canonical
                    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except (json.JSONDecodeError, OSError):
                    pass
            path.unlink(missing_ok=True)

    for cluster in report.clusters:
        if cluster.review and not auto:
            continue
        if len(cluster.member_ids) < 2:
            continue
        canonical = cluster.canonical_id
        for drop in cluster.member_ids:
            if drop == canonical:
                continue
            _unlink_temp(drop)
            merged += 1
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write("merged %s -> %s\n" % (drop, canonical))

    return CleanupReport(
        clusters=report.clusters,
        orphan_files=report.orphan_files,
        already_labeled=report.already_labeled,
        dry_run=False,
        merged_count=merged,
    )


def _cli_cleanup(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit duplicate temp item PNGs in items/")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--merge", action="store_true", help="Delete duplicate temp PNG/JSON files")
    parser.add_argument("--extra", action="append", default=[], help="Extra dirs to scan (unused in v1)")
    args = parser.parse_args(argv)
    report = audit_seen_duplicates(extra_dirs=args.extra)
    if args.merge:
        report = merge_duplicate_clusters(report)
    else:
        report = CleanupReport(
            clusters=report.clusters,
            orphan_files=report.orphan_files,
            already_labeled=report.already_labeled,
            dry_run=True,
            merged_count=0,
        )
    print(report.to_text())
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        raise SystemExit(_cli_cleanup())
    print("Usage: python -m bot_match_index cleanup [--dry-run|--merge] [--extra DIR]")
    raise SystemExit(1)
