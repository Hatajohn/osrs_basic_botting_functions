"""
Action-strip template paths and grayscale loading (shared by action + template find).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

_IMAGES = Path(__file__).resolve().parent / "images"
_EXODIA_DIR = _IMAGES.parent
FISHING_TEXT_TEMPLATE = "Fishing_text.png"
NOT_FISHING_TEXT_TEMPLATE = "Not_fishing_text.png"


def resolve_action_template_path(filename: str) -> Optional[Path]:
    """``Fishing_text.png`` / ``Not_fishing_text.png`` — same search order as ``bot_eyes``."""
    name = (filename or "").strip()
    if not name:
        return None
    stem = name[:-4] if name.lower().endswith(".png") else name
    candidates: list[Path] = []
    raw_dir = os.environ.get("EXODIA_IMAGES_DIR", "").strip()
    if raw_dir:
        base = Path(raw_dir).expanduser()
        candidates.extend([base / name, base / ("%s.png" % stem)])
    candidates.extend(
        [
            Path.cwd() / "images" / name,
            Path.cwd() / "images" / ("%s.png" % stem),
            _EXODIA_DIR.parent / "images" / name,
            _EXODIA_DIR.parent / "images" / ("%s.png" % stem),
            _IMAGES / name,
            _IMAGES / ("%s.png" % stem),
        ]
    )
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.resolve()
    return None


def load_template_gray(path: str) -> Optional[np.ndarray]:
    if not path or not os.path.isfile(path):
        return None
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None or raw.size == 0:
        return None
    if raw.ndim == 2:
        return raw
    if raw.shape[2] == 4:
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)


def action_template_paths_ok() -> Dict[str, bool]:
    return {
        FISHING_TEXT_TEMPLATE: resolve_action_template_path(FISHING_TEXT_TEMPLATE) is not None,
        NOT_FISHING_TEXT_TEMPLATE: resolve_action_template_path(NOT_FISHING_TEXT_TEMPLATE)
        is not None,
    }


__all__ = [
    "FISHING_TEXT_TEMPLATE",
    "NOT_FISHING_TEXT_TEMPLATE",
    "action_template_paths_ok",
    "load_template_gray",
    "resolve_action_template_path",
]
