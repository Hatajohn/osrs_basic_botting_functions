"""
Playspace geometry helpers — screen anchors without ``BotEyes``.

``global_center_from_client_rect`` mirrors ``BotEyes.find_center``: character anchor
slightly left and below the geometric client center (used for pan/walk in ``bot_search``).
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple

__all__ = [
    "global_center_from_client_rect",
    "local_center_from_client_rect",
]


def local_center_from_client_rect(client_rect: Sequence[int]) -> Tuple[int, int]:
    """Character anchor in client-local coordinates (origin = client top-left)."""
    if len(client_rect) != 4:
        raise ValueError("client_rect must be [left, top, width, height]")
    w, h = int(client_rect[2]), int(client_rect[3])
    return math.floor(w / 2) - 20, math.floor(h / 2) + 25


def global_center_from_client_rect(client_rect: Sequence[int]) -> Tuple[int, int]:
    """Character anchor in Win32 screen coordinates (same as ``BotEyes.global_center``)."""
    if len(client_rect) != 4:
        raise ValueError("client_rect must be [left, top, width, height]")
    left, top = int(client_rect[0]), int(client_rect[1])
    lx, ly = local_center_from_client_rect(client_rect)
    return left + lx, top + ly
