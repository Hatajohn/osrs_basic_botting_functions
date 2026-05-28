"""
User-managed template watchlist for the perception stream.

Resolution order for world templates (``WatchlistResolver.world_template_names``):

1. ``world_templates`` in ``perception_stream_control.json`` (UI hot-reload)
2. Enabled ``region: world`` entries in ``template_watchlist.json``
3. ``EXODIA_WORLD_TEMPLATES`` env
4. Default ``osrs_infernalEel``
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_EXODIA_DIR = Path(__file__).resolve().parent


def default_watchlist_path() -> Path:
    raw = os.environ.get("EXODIA_TEMPLATE_WATCHLIST", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_EXODIA_DIR / p).resolve()
    return (_EXODIA_DIR / "ExodiaBotUI" / "template_watchlist.json").resolve()


def _normalize_stem(template: str) -> str:
    stem = template.strip()
    if stem.lower().endswith(".png"):
        return stem[:-4]
    return stem


@dataclass(frozen=True)
class WatchlistEntry:
    id: str
    template: str
    region: str
    enabled: bool = True


def parse_watchlist_data(data: Any) -> List[WatchlistEntry]:
    if not isinstance(data, dict):
        return []
    entries_raw = data.get("entries")
    if not isinstance(entries_raw, list):
        return []
    out: List[WatchlistEntry] = []
    for i, raw in enumerate(entries_raw):
        if not isinstance(raw, dict):
            continue
        template = str(raw.get("template", "")).strip()
        if not template:
            continue
        region = str(raw.get("region", "world")).strip().lower()
        if region not in ("world", "inventory"):
            region = "world"
        entry_id = str(raw.get("id", "")).strip() or ("e%d" % i)
        enabled = raw.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.lower() not in ("0", "false", "no", "off")
        out.append(
            WatchlistEntry(
                id=entry_id,
                template=_normalize_stem(template),
                region=region,
                enabled=bool(enabled),
            )
        )
    return out


def load_watchlist_file(path: Optional[Path] = None) -> List[WatchlistEntry]:
    p = path or default_watchlist_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return parse_watchlist_data(data)
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def _read_control_world_templates(control_file: Optional[Path]) -> Optional[List[str]]:
    if control_file is None or not control_file.is_file():
        return None
    try:
        data = json.loads(control_file.read_text(encoding="utf-8"))
        raw = data.get("world_templates")
        if raw is None:
            return None
        if not isinstance(raw, list):
            return None
        names = [_normalize_stem(str(t)) for t in raw if str(t).strip()]
        return names
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _read_control_inventory_templates(control_file: Optional[Path]) -> Optional[List[str]]:
    if control_file is None or not control_file.is_file():
        return None
    try:
        data = json.loads(control_file.read_text(encoding="utf-8"))
        raw = data.get("inventory_templates")
        if raw is None:
            return None
        if not isinstance(raw, list):
            return None
        return [_normalize_stem(str(t)) for t in raw if str(t).strip()]
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def resolve_world_template_names(
    entries: Sequence[WatchlistEntry],
    *,
    control_templates: Optional[Sequence[str]] = None,
) -> List[str]:
    if control_templates is not None:
        return [_normalize_stem(t) for t in control_templates if str(t).strip()]
    from_entries = [
        _normalize_stem(e.template)
        for e in entries
        if e.enabled and e.region == "world"
    ]
    if from_entries:
        return from_entries
    raw = os.environ.get("EXODIA_WORLD_TEMPLATES", "").strip()
    if raw:
        return [_normalize_stem(t) for t in raw.split(",") if t.strip()]
    return ["osrs_infernalEel"]


def enabled_inventory_templates(entries: Sequence[WatchlistEntry]) -> List[str]:
    return [
        _normalize_stem(e.template)
        for e in entries
        if e.enabled and e.region == "inventory"
    ]


def inventory_watch_matches(
    slot_items: Sequence[Sequence[Optional[str]]],
    watch_templates: Sequence[str],
) -> List[Dict[str, Any]]:
    """Map inventory watch templates to occupied slots via identified slot labels."""
    if not watch_templates or not slot_items:
        return []
    stems = [_normalize_stem(t) for t in watch_templates]
    out: List[Dict[str, Any]] = []
    for template in stems:
        slots: List[List[int]] = []
        for row, row_items in enumerate(slot_items):
            if not isinstance(row_items, (list, tuple)):
                continue
            for col, label in enumerate(row_items):
                if label is None or label == "":
                    continue
                norm = _normalize_stem(str(label)).lower()
                if norm == template.lower() or (norm.startswith("tmp:") and template.lower() in norm):
                    slots.append([row, col])
        out.append({"template": template, "slots": slots})
    return out


def locate_inventory_watch_templates(
    client_bgr: Any,
    inventory_rect: Sequence[int],
    client_rect: Sequence[int],
    watch_templates: Sequence[str],
    *,
    slot_items: Optional[Sequence[Sequence[Optional[str]]]] = None,
) -> List[Dict[str, Any]]:
    """
    Locate watched inventory templates via per-slot template match.

    Falls back to ``slot_items`` label match when the PNG is missing or no match is found.
    """
    if not watch_templates or len(inventory_rect) != 4 or len(client_rect) != 4:
        return []

    from bot_inventory_items import (
        locate_named_template_in_inventory,
        resolve_inventory_template_path,
        slot_at_client_point,
    )

    label_fallback = {
        entry["template"]: entry["slots"]
        for entry in inventory_watch_matches(slot_items or [], watch_templates)
    }

    out: List[Dict[str, Any]] = []
    for raw in watch_templates:
        stem = _normalize_stem(raw)
        if not stem:
            continue
        if resolve_inventory_template_path(stem) is None:
            slots_set: set[tuple[int, int]] = set()
            if stem in label_fallback:
                for slot in label_fallback[stem]:
                    if len(slot) >= 2:
                        slots_set.add((int(slot[0]), int(slot[1])))
            out.append(
                {
                    "template": stem,
                    "slots": [[r, c] for r, c in sorted(slots_set)],
                    "best_score": None,
                    "source": "labels" if slots_set else "missing_template",
                }
            )
            continue
        matches, _err = locate_named_template_in_inventory(
            client_bgr,
            inventory_rect,
            client_rect,
            stem,
        )
        slots_set: set[tuple[int, int]] = set()
        points: List[Dict[str, Any]] = []
        best_score: Optional[float] = None
        source = "none"
        if matches:
            source = "template"
            for match in matches:
                rc = slot_at_client_point(
                    int(match.client_xy[0]),
                    int(match.client_xy[1]),
                    inventory_rect,
                )
                if rc is None:
                    continue
                row, col = int(rc[0]), int(rc[1])
                slots_set.add((row, col))
                score = float(match.score)
                points.append(
                    {
                        "slot": [row, col],
                        "client_xy": [int(match.client_xy[0]), int(match.client_xy[1])],
                        "score": round(score, 4),
                    }
                )
                if best_score is None or score > best_score:
                    best_score = score
        if not slots_set and stem in label_fallback:
            source = "labels"
            for slot in label_fallback[stem]:
                if len(slot) >= 2:
                    slots_set.add((int(slot[0]), int(slot[1])))
        out.append(
            {
                "template": stem,
                "slots": [[r, c] for r, c in sorted(slots_set)],
                "points": points,
                "best_score": round(best_score, 4) if best_score is not None else None,
                "source": source,
            }
        )
    return out


class WatchlistResolver:
    """Poll watchlist + control file; cache resolved template lists."""

    def __init__(
        self,
        *,
        watchlist_path: Optional[Path] = None,
        control_file: Optional[Path] = None,
    ) -> None:
        self._watchlist_path = watchlist_path or default_watchlist_path()
        self._control_file = control_file
        self._lock = threading.Lock()
        self._entries: List[WatchlistEntry] = []
        self._world_templates: List[str] = []
        self._inventory_templates: List[str] = []
        self._watchlist_mtime: float = 0.0
        self._control_mtime: float = 0.0
        self.refresh(force=True)

    def refresh(self, *, force: bool = False) -> bool:
        watch_mtime = 0.0
        if self._watchlist_path.is_file():
            try:
                watch_mtime = self._watchlist_path.stat().st_mtime
            except OSError:
                watch_mtime = 0.0

        control_mtime = 0.0
        if self._control_file is not None and self._control_file.is_file():
            try:
                control_mtime = self._control_file.stat().st_mtime
            except OSError:
                control_mtime = 0.0

        if (
            not force
            and watch_mtime == self._watchlist_mtime
            and control_mtime == self._control_mtime
        ):
            return False

        entries = load_watchlist_file(self._watchlist_path)
        control_world = _read_control_world_templates(self._control_file)
        if control_world is not None and len(control_world) > 0:
            world = [_normalize_stem(t) for t in control_world if str(t).strip()]
        elif entries:
            world = resolve_world_template_names(entries, control_templates=None)
        elif control_world is not None and self._watchlist_path.is_file():
            world = []
        else:
            world = resolve_world_template_names([], control_templates=None)

        control_inventory = _read_control_inventory_templates(self._control_file)
        if control_inventory is not None and len(control_inventory) > 0:
            inventory = [_normalize_stem(t) for t in control_inventory if str(t).strip()]
        elif entries:
            inventory = enabled_inventory_templates(entries)
        elif control_inventory is not None and self._watchlist_path.is_file():
            inventory = []
        else:
            inventory = enabled_inventory_templates(entries)

        with self._lock:
            self._watchlist_mtime = watch_mtime
            self._control_mtime = control_mtime
            self._entries = entries
            self._world_templates = world
            self._inventory_templates = inventory
        return True

    def world_template_names(self) -> List[str]:
        with self._lock:
            return list(self._world_templates)

    def inventory_template_names(self) -> List[str]:
        with self._lock:
            return list(self._inventory_templates)

    def entries(self) -> List[WatchlistEntry]:
        with self._lock:
            return list(self._entries)


__all__ = [
    "WatchlistEntry",
    "WatchlistResolver",
    "default_watchlist_path",
    "enabled_inventory_templates",
    "inventory_watch_matches",
    "locate_inventory_watch_templates",
    "load_watchlist_file",
    "parse_watchlist_data",
    "resolve_world_template_names",
]
