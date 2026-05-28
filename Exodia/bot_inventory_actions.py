"""Inventory actions layer: grid slot clicks and OSRS use-item-on (by slot or label).

Use this when you need to click inventory cells or use one item on another without
template matching. Coordinates are Win32 screen space from ``inventory_slot_screen_xy``
and ``client_rect``. Template-based use-on lives in ``bot_actions.use_x_on_y`` (imports
``pick_distinct_screen_points`` and ``clear_inventory_hover`` from here).
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from bot_eyes import INV_COLS, INV_ROWS, inventory_slot_screen_xy
import bot_env as Env


@dataclass(frozen=True)
class UseItemOnResult:
    """Question: What happened when I tried to use one inventory item on another?

    Fields: ``ok``, ``reason``, optional ``missing_item``, ``source_slot``, ``dest_slot``.
    Bool-coerces to ``ok``. Factory helpers: ``success()``, ``fail()``.
    """

    ok: bool
    reason: str = "ok"
    missing_item: Optional[str] = None
    source_slot: Optional[Tuple[int, int]] = None
    dest_slot: Optional[Tuple[int, int]] = None

    def __bool__(self) -> bool:
        return self.ok

    @classmethod
    def success(
        cls,
        source_slot: Tuple[int, int],
        dest_slot: Tuple[int, int],
    ) -> UseItemOnResult:
        return cls(True, "ok", source_slot=source_slot, dest_slot=dest_slot)

    @classmethod
    def fail(
        cls,
        reason: str,
        *,
        missing_item: Optional[str] = None,
        source_slot: Optional[Tuple[int, int]] = None,
        dest_slot: Optional[Tuple[int, int]] = None,
    ) -> UseItemOnResult:
        return cls(
            False,
            reason,
            missing_item=missing_item,
            source_slot=source_slot,
            dest_slot=dest_slot,
        )


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


def slot_manhattan(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """Grid steps between two inventory slots ``(row, col)``."""
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))


def closest_slot(
    reference: Tuple[int, int],
    candidates: Sequence[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    """Question: Which inventory slot is nearest another slot on the grid?

    Manhattan distance; ties break toward top-left ``(row, col)``.
    """
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda c: (slot_manhattan(reference, c), int(c[0]), int(c[1])),
    )


def pick_distinct_screen_points(
    sources: Sequence[Sequence[int]],
    dests: Sequence[Sequence[int]],
    *,
    min_sep_px: Optional[int] = None,
) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """
    Choose source and destination screen points for use-on.

    Picks the destination **closest** to the source (screen distance). Returns
    ``(None, None)`` when every destination lies on the source point.
    """
    sep = min_sep_px
    if sep is None:
        sep = _env_int("EXODIA_INV_USE_ON_MIN_SEP_PX", 8)
    src_pts = sorted(
        {(int(p[0]), int(p[1])) for p in sources},
        key=lambda p: (p[0], p[1]),
    )
    dst_pts = [(int(p[0]), int(p[1])) for p in dests]
    for src in src_pts:
        pool = [
            dst
            for dst in dst_pts
            if math.hypot(dst[0] - src[0], dst[1] - src[1]) >= sep
        ]
        if pool:
            dst = min(
                pool,
                key=lambda d: (
                    math.hypot(d[0] - src[0], d[1] - src[1]),
                    d[0],
                    d[1],
                ),
            )
            return src, dst
    return None, None


def client_screen_center(client_rect: Sequence[int]) -> Tuple[int, int]:
    """Center of the game client in Win32 screen coordinates."""
    left, top, w, h = (int(v) for v in client_rect[:4])
    return left + w // 2, top + h // 2


def focus_runelite(*, title: str = "RuneLite") -> bool:
    """Bring RuneLite to foreground when using ``wsl_ps`` input."""
    import bot_env as Env

    if Env.input_backend_label() != "wsl_ps":
        return False
    return bool(Env.wsl_windows_focus_window(title))


def move_mouse_to_screen(
    xy: Sequence[int],
    *,
    rad: int = 12,
    duration: float = 0.22,
    move_profile: str = "open",
    hover_clear_s: Optional[float] = None,
) -> None:
    """Move cursor and wait so item hover text clears before captures or clicks."""
    from bot_arms import BotArms

    BotArms().move_mouse(
        [int(xy[0]), int(xy[1])],
        rad=rad,
        duration=duration,
        move_profile=move_profile,
    )
    settle = hover_clear_s
    if settle is None:
        settle = _env_float("EXODIA_INV_HOVER_CLEAR_S", 0.35)
    if settle > 0:
        time.sleep(settle)


def clear_inventory_hover(
    client_rect: Sequence[int],
    *,
    rad: int = 12,
    duration: float = 0.22,
    hover_clear_s: Optional[float] = None,
) -> Tuple[int, int]:
    """Question: How do I move the mouse off inventory so item tooltips clear?

    Moves to client center (also used before use-on clicks). Returns that screen point.
    Settle time: ``EXODIA_INV_HOVER_CLEAR_S``.
    """
    center = client_screen_center(client_rect)
    move_mouse_to_screen(center, rad=rad, duration=duration, hover_clear_s=hover_clear_s)
    return center


def inventory_slot_screen_point(
    inventory_rect: Sequence[int],
    client_rect: Sequence[int],
    row: int,
    col: int,
) -> Optional[Tuple[int, int]]:
    """Center of slot ``(row, col)`` in Win32 screen coordinates."""
    if not (0 <= row < INV_ROWS and 0 <= col < INV_COLS):
        return None
    return inventory_slot_screen_xy(inventory_rect, client_rect, row, col)


def click_inventory_slot(
    inventory_rect: Sequence[int],
    client_rect: Sequence[int],
    row: int,
    col: int,
    *,
    arms=None,
    rad: Optional[int] = None,
    duration: float = 0.12,
    move_profile: str = "tight",
    focus: bool = True,
) -> bool:
    """Question: How do I left-click one inventory grid cell?

    Moves to slot center and clicks. Returns ``False`` if ``(row, col)`` is out of range.
    Click jitter: ``EXODIA_INV_CLICK_RAD``.
    """
    xy = inventory_slot_screen_point(inventory_rect, client_rect, row, col)
    if xy is None:
        return False
    if focus:
        focus_runelite()
    if arms is None:
        from bot_arms import BotArms

        arms = BotArms()
    click_rad = rad if rad is not None else int(os.environ.get("EXODIA_INV_CLICK_RAD", "6"))
    arms.click_at(xy, rad=click_rad, duration=duration, move_profile=move_profile)
    return True


def use_inventory_slot_on_slot(
    inventory_rect: Sequence[int],
    client_rect: Sequence[int],
    source: Tuple[int, int],
    destination: Tuple[int, int],
    *,
    arms=None,
    center_first: bool = True,
    focus: bool = True,
    click_rad: Optional[int] = None,
    between_clicks_s: Optional[float] = None,
) -> UseItemOnResult:
    """Question: How do I use the item in one inventory slot on another slot?

    ``source`` / ``destination`` are ``(row, col)``. When ``center_first`` is true,
    clears hover via ``clear_inventory_hover`` before the first click. Gap between
    clicks: ``EXODIA_INV_USE_ON_GAP_S``.
    """
    sr, sc = (int(source[0]), int(source[1]))
    dr, dc = (int(destination[0]), int(destination[1]))
    if not (0 <= sr < INV_ROWS and 0 <= sc < INV_COLS):
        return UseItemOnResult.fail("source_slot_invalid", source_slot=(sr, sc))
    if not (0 <= dr < INV_ROWS and 0 <= dc < INV_COLS):
        return UseItemOnResult.fail("dest_slot_invalid", dest_slot=(dr, dc))
    if (sr, sc) == (dr, dc):
        return UseItemOnResult.fail(
            "dest_not_found",
            dest_slot=(dr, dc),
            source_slot=(sr, sc),
        )
    if focus:
        focus_runelite()
        time.sleep(Env.pre_click_settle_s())
    if center_first:
        clear_inventory_hover(client_rect)
    if arms is None:
        from bot_arms import BotArms

        arms = BotArms()
    if not click_inventory_slot(
        inventory_rect,
        client_rect,
        sr,
        sc,
        arms=arms,
        rad=click_rad,
        focus=False,
    ):
        return UseItemOnResult.fail(
            "source_click_failed",
            source_slot=(sr, sc),
            dest_slot=(dr, dc),
        )
    gap = between_clicks_s
    if gap is None:
        time.sleep(Env.use_on_click_gap_s())
    else:
        time.sleep(max(0.006, float(gap) / Env.mouse_speed_factor()))
    if not click_inventory_slot(
        inventory_rect,
        client_rect,
        dr,
        dc,
        arms=arms,
        rad=click_rad,
        focus=False,
    ):
        return UseItemOnResult.fail(
            "dest_click_failed",
            source_slot=(sr, sc),
            dest_slot=(dr, dc),
        )
    return UseItemOnResult.success((sr, sc), (dr, dc))


def slots_matching_item(
    slot_items: Sequence[Sequence[Optional[str]]],
    item_name: str,
    *,
    occupied_only: bool = True,
) -> List[Tuple[int, int]]:
    """All ``(row, col)`` where grid label equals ``item_name`` (case-insensitive)."""
    want = item_name.strip().lower()
    out: List[Tuple[int, int]] = []
    for row in range(min(INV_ROWS, len(slot_items))):
        for col in range(min(INV_COLS, len(slot_items[row]))):
            label = slot_items[row][col]
            if label is None:
                continue
            if occupied_only and label == "?":
                continue
            if str(label).strip().lower() == want:
                out.append((row, col))
    return out


def use_named_item_on_named_item(
    inventory_rect: Sequence[int],
    client_rect: Sequence[int],
    slot_items: Sequence[Sequence[Optional[str]]],
    source_item: str,
    dest_item: str,
    *,
    arms=None,
    source_slot: Optional[Tuple[int, int]] = None,
    dest_slot: Optional[Tuple[int, int]] = None,
    center_first: bool = True,
) -> UseItemOnResult:
    """Question: How do I use one labeled inventory item on another by item name?

    Calls: ``slots_matching_item`` → ``closest_slot`` (when slots omitted) →
    ``use_inventory_slot_on_slot``. Omitted slots: stable top-left source, **closest**
    dest to source (Manhattan). For PNG templates use ``bot_actions.use_x_on_y`` instead.
    """
    src_candidates = slots_matching_item(slot_items, source_item)
    dst_candidates = slots_matching_item(slot_items, dest_item)

    if source_slot is not None:
        if source_slot not in src_candidates:
            return UseItemOnResult.fail(
                "source_not_found",
                missing_item=source_item,
                source_slot=source_slot,
            )
        src = source_slot
    elif not src_candidates:
        return UseItemOnResult.fail("source_not_found", missing_item=source_item)
    else:
        src = sorted(src_candidates, key=lambda s: (s[0], s[1]))[0]

    if dest_slot is not None:
        if dest_slot not in dst_candidates:
            return UseItemOnResult.fail(
                "dest_not_found",
                missing_item=dest_item,
                dest_slot=dest_slot,
                source_slot=src,
            )
        if dest_slot == src:
            return UseItemOnResult.fail(
                "dest_not_found",
                missing_item=dest_item,
                dest_slot=dest_slot,
                source_slot=src,
            )
        dst = dest_slot
    else:
        dst_pool = [s for s in dst_candidates if s != src]
        if not dst_pool:
            return UseItemOnResult.fail(
                "dest_not_found",
                missing_item=dest_item,
                source_slot=src,
            )
        dst = closest_slot(src, dst_pool)
        if dst is None:
            return UseItemOnResult.fail(
                "dest_not_found",
                missing_item=dest_item,
                source_slot=src,
            )

    result = use_inventory_slot_on_slot(
        inventory_rect,
        client_rect,
        src,
        dst,
        arms=arms,
        center_first=center_first,
    )
    if not result.ok:
        return result
    return UseItemOnResult.success(src, dst)
