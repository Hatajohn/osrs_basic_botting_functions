"""
Playspace search helpers: camera pan and ground-click relocation.

Use ``search_with_camera_pan`` when the target may appear after rotating the camera.
Add ``relocate`` / ``max_relocate_attempts`` to click the ground and walk the character
when pans alone do not reveal a match (OSRS: click tile in the main view).
"""
from __future__ import annotations

import random
import time
from typing import Callable, List, Optional, Sequence, Tuple

Point = List[int]  # [screen_x, screen_y]

WALK_DIRECTIONS = ("north", "east", "south", "west")

__all__ = [
    "WALK_DIRECTIONS",
    "click_random_hit",
    "ground_click_target",
    "playspace_search_roi",
    "search_with_camera_pan",
    "walk_direction_for_attempt",
]


def playspace_search_roi(
    frame_width: int,
    frame_height: int,
    *,
    right_margin: int = 240,
    bottom_margin: int = 180,
) -> Optional[List[int]]:
    """
    Client-local ROI excluding inventory (right) and chat/footer (bottom).

    Returns ``[x, y, w, h]`` or ``None`` if the frame is too small.
    """
    w0, h0 = int(frame_width), int(frame_height)
    if w0 < 100 or h0 < 100:
        return None
    return [0, 0, max(100, w0 - right_margin), max(100, h0 - bottom_margin)]


def walk_direction_for_attempt(attempt_index: int) -> str:
    """Rotate through N/E/S/W so relocation does not always walk the same way."""
    return WALK_DIRECTIONS[int(attempt_index) % len(WALK_DIRECTIONS)]


def ground_click_target(
    client_rect: Sequence[int],
    anchor_screen: Sequence[int],
    direction: str,
    *,
    distance_frac: float = 0.32,
    y_jitter_frac: float = 0.08,
) -> Point:
    """
    Screen coordinate to click the ground and walk ``direction`` from ``anchor_screen``.

    ``client_rect`` is ``[left, top, width, height]`` (screen). ``anchor_screen`` is
    usually ``BotEyes.global_center``. Clicks stay in the left playspace (not on inventory).
    """
    if len(client_rect) != 4 or len(anchor_screen) < 2:
        return [int(anchor_screen[0]), int(anchor_screen[1])]
    left, top, cw, ch = (int(client_rect[i]) for i in range(4))
    ax, ay = int(anchor_screen[0]), int(anchor_screen[1])
    play_right = left + max(120, int(cw * 0.72))
    dx = max(80, int(cw * distance_frac))
    dy = max(60, int(ch * distance_frac))
    jx = int(cw * y_jitter_frac * (random.random() - 0.5))
    jy = int(ch * y_jitter_frac * (random.random() - 0.5))
    direction = direction.lower()
    if direction == "north":
        tx, ty = ax + jx, ay - dy
    elif direction == "south":
        tx, ty = ax + jx, ay + dy
    elif direction == "west":
        tx, ty = ax - dx, ay + jy
    else:  # east or default
        tx, ty = ax + dx, ay + jy
    tx = max(left + 40, min(play_right - 40, tx))
    ty = max(top + 80, min(top + ch - 120, ty))
    return [tx, ty]


def search_with_camera_pan(
    locate: Callable[[], Sequence[Point]],
    pan: Callable[[], None],
    *,
    max_pan_attempts: int,
    sleep_after_pan_s: float = 0.6,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_abort: Callable[[], bool] = lambda: False,
    on_miss: Optional[Callable[[int, int], None]] = None,
    relocate: Optional[Callable[[int, int], None]] = None,
    max_relocate_attempts: int = 0,
    sleep_after_relocate_s: float = 3.0,
    on_relocate: Optional[Callable[[int, int], None]] = None,
) -> List[Point]:
    """
    Call ``locate()``; on empty results run ``pan()`` and retry.

    When pans are exhausted and ``max_relocate_attempts`` > 0, calls ``relocate(attempt, max)``
    (e.g. ground click to walk), waits, and locates again.

    Returns the first non-empty hit list, or ``[]`` after all attempts.
    ``on_miss(attempt_index, max_pan_attempts)`` runs when a pan is about to happen.
    """
    max_pan_attempts = max(0, int(max_pan_attempts))
    for attempt in range(max_pan_attempts + 1):
        if should_abort():
            return []
        hits = list(locate())
        if hits:
            return hits
        if attempt >= max_pan_attempts:
            break
        if on_miss is not None:
            on_miss(attempt + 1, max_pan_attempts)
        pan()
        sleep_fn(max(0.0, float(sleep_after_pan_s)))

    max_relocate_attempts = max(0, int(max_relocate_attempts))
    for walk_i in range(max_relocate_attempts):
        if should_abort():
            return []
        if relocate is not None:
            if on_relocate is not None:
                on_relocate(walk_i + 1, max_relocate_attempts)
            relocate(walk_i + 1, max_relocate_attempts)
            sleep_fn(max(0.0, float(sleep_after_relocate_s)))
        hits = list(locate())
        if hits:
            return hits
    return []


def click_random_hit(
    click_fn: Callable[[Point], None],
    hits: Sequence[Point],
) -> bool:
    """Click a random entry from ``hits`` using ``click_fn(point)``. Returns ``False`` if empty."""
    if not hits:
        return False
    click_fn(random.choice(list(hits)))
    return True
