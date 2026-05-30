"""
Read/write ``captures/perception_stream_control.json`` for the perception stream.

Bots set ``pan_in_progress`` during camera pan so ``WorldVisionProcessor`` can
clear world tracks instead of associating stale screen coordinates.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from bot_runtime import write_json_atomic
from bot_template_watchlist import _normalize_stem

_EXODIA_DIR = Path(__file__).resolve().parent


def default_stream_control_path() -> Path:
    raw = os.environ.get("EXODIA_STREAM_CONTROL_FILE", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_EXODIA_DIR / p).resolve()
    return (_EXODIA_DIR / "captures" / "perception_stream_control.json").resolve()


def read_stream_control(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or default_stream_control_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def read_pan_in_progress(path: Optional[Path] = None) -> bool:
    return bool(read_stream_control(path).get("pan_in_progress"))


def set_pan_in_progress(active: bool, path: Optional[Path] = None) -> None:
    """Atomically set ``pan_in_progress`` while preserving other control keys."""
    p = path or default_stream_control_path()
    data = read_stream_control(p)
    data["pan_in_progress"] = bool(active)
    write_json_atomic(p, data)


def set_world_templates(templates: Sequence[str], path: Optional[Path] = None) -> None:
    """Atomically set ``world_templates`` while preserving other control keys."""
    p = path or default_stream_control_path()
    data = read_stream_control(p)
    data["world_templates"] = [
        _normalize_stem(str(t)) for t in templates if str(t).strip()
    ]
    write_json_atomic(p, data)


def infernal_spot_world_stems() -> List[str]:
    """Resolve infernal fishing spot template stems from ``EXODIA_INFERNAL_SPOT_TEMPLATES``."""
    from bot_world_objects import resolve_world_template_file

    raw = os.environ.get(
        "EXODIA_INFERNAL_SPOT_TEMPLATES", "osrs_infernalEel.png,infernal_eel_spot.png"
    )
    stems: List[str] = []
    seen: set[str] = set()
    for template in raw.split(","):
        template = template.strip()
        if not template:
            continue
        stem, tpl_path = resolve_world_template_file(template)
        if not tpl_path:
            continue
        norm = _normalize_stem(stem)
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        stems.append(norm)
    return stems


def configure_infernal_world_watchlist(path: Optional[Path] = None) -> List[str]:
    """Write infernal spot stems to the stream control file (preserves ``pan_in_progress``)."""
    stems = infernal_spot_world_stems()
    if not stems:
        stems = ["osrs_infernalEel"]
    set_world_templates(stems, path)
    return stems


def stream_pan_signal(path: Optional[Path] = None) -> Callable[[bool], None]:
    """Callback for ``search_with_camera_pan(..., signal_pan=...)``."""

    def _signal(active: bool) -> None:
        try:
            set_pan_in_progress(active, path)
        except OSError:
            pass

    return _signal


__all__ = [
    "configure_infernal_world_watchlist",
    "default_stream_control_path",
    "infernal_spot_world_stems",
    "read_pan_in_progress",
    "read_stream_control",
    "set_pan_in_progress",
    "set_world_templates",
    "stream_pan_signal",
]
