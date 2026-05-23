"""
Load and save manual RuneLite client window geometry (Windows screen coordinates).

Used when xdotool cannot see Windows RuneLite from WSL. Pair with
``EXODIA_CAPTURE_BACKEND=wsl_ps`` and ``EXODIA_INPUT_BACKEND=wsl_ps``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

Rect = List[int]

_DEFAULT_FILE = Path(__file__).resolve().parent / "client_rect.json"

__all__ = [
    "default_client_rect_path",
    "load_client_rect",
    "save_client_rect",
    "rect_from_env",
]


def default_client_rect_path() -> Path:
    raw = os.environ.get("EXODIA_CLIENT_RECT_FILE", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_FILE


def load_client_rect(path: Optional[Path] = None) -> Optional[Rect]:
    """Return ``[left, top, width, height]`` or ``None`` if file missing/invalid."""
    p = path if path is not None else default_client_rect_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        rect = data.get("rect") or data
        parts = [int(rect[k]) for k in ("left", "top", "width", "height")]
        if parts[2] <= 0 or parts[3] <= 0:
            return None
        return parts
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_client_rect(rect: Rect, path: Optional[Path] = None, note: str = "") -> Path:
    p = path if path is not None else default_client_rect_path()
    payload = {
        "rect": {
            "left": int(rect[0]),
            "top": int(rect[1]),
            "width": int(rect[2]),
            "height": int(rect[3]),
        },
        "format": "left,top,width,height",
        "coordinate_space": "windows_primary",
        "note": note,
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def rect_from_env() -> Optional[Rect]:
    raw = os.environ.get("EXODIA_CLIENT_RECT", "").strip()
    if not raw:
        return None
    parts = [int(x.strip()) for x in raw.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("EXODIA_CLIENT_RECT must be LEFT,TOP,WIDTH,HEIGHT")
    return parts
