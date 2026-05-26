"""Helpers for inventory vs playspace template click targeting."""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple


def inventory_global_rect(eyes) -> Optional[List[int]]:
    if eyes.inventory_global is not None and len(eyes.inventory_global) == 4:
        return [int(v) for v in eyes.inventory_global]
    if (
        eyes.inventory_rect is not None
        and len(eyes.inventory_rect) == 4
        and eyes.client_rect is not None
        and len(eyes.client_rect) == 4
    ):
        cr = eyes.client_rect
        ir = eyes.inventory_rect
        return [cr[0] + ir[0], cr[1] + ir[1], ir[2], ir[3]]
    return None


def point_in_rect(px: int, py: int, rect: Sequence[int]) -> bool:
    x, y, w, h = (int(rect[i]) for i in range(4))
    return x <= px < x + w and y <= py < y + h


def playspace_search_roi(eyes) -> Optional[List[int]]:
    """Client-local ROI above the inventory panel (exclude inv for world clicks)."""
    if eyes.curr_client is None or getattr(eyes.curr_client, "size", 0) == 0:
        return None
    h, w = eyes.curr_client.shape[:2]
    if eyes.inventory_rect is not None and len(eyes.inventory_rect) == 4:
        iy = int(eyes.inventory_rect[1])
        if iy >= max(20, int(h * 0.12)):
            return [0, 0, int(w), iy]
    return None


def filter_matches_outside_inventory(eyes, matches: List[Any]) -> Tuple[List[Any], int]:
    rect = inventory_global_rect(eyes)
    if not rect or not matches:
        return matches, 0
    kept = []
    dropped = 0
    for m in matches:
        sx, sy = m.screen_xy[0], m.screen_xy[1]
        if point_in_rect(sx, sy, rect):
            dropped += 1
        else:
            kept.append(m)
    return kept, dropped


def slot_label_for_match(eyes, match) -> Optional[str]:
    if eyes.inventory_rect is None or len(eyes.inventory_rect) != 4:
        return None
    from bot_inventory_items import slot_at_client_point

    slot = slot_at_client_point(
        int(match.client_xy[0]),
        int(match.client_xy[1]),
        eyes.inventory_rect,
    )
    if slot is None:
        return None
    return "row=%d col=%d" % (slot[0], slot[1])
