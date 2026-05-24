"""
Inventory mouse actions: center cursor, click a grid slot, use slot-on-slot (OSRS use-item).

Coordinates are Win32 screen space from ``inventory_slot_screen_xy`` + ``client_rect``.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from bot_eyes import INV_COLS, INV_ROWS, inventory_slot_screen_xy


@dataclass(frozen=True)
class UseItemOnResult:
    """Outcome of a use-item-on attempt (slot or template based)."""

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
    """Move mouse to client center; return that point."""
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
    """Move to slot center and left-click. Returns ``False`` if coords invalid."""
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
    """
    OSRS use-item: click **source** slot, then **destination** slot.

    ``source`` / ``destination`` are ``(row, col)``. When ``center_first`` is true,
    the cursor moves to the client center before the first click (clears hover text).
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
        time.sleep(0.2)
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
        gap = _env_float("EXODIA_INV_USE_ON_GAP_S", 0.18)
    time.sleep(max(0.05, gap))
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
    """
    Use one named inventory item on another (e.g. flax on flax).

    Picks random matching slots when ``source_slot`` / ``dest_slot`` are omitted.
    Source and destination must be **different** slots. If only one matching
    destination location exists and it equals the source, returns ``dest_not_found``.
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
        src = random.choice(src_candidates)

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
        dst = random.choice(dst_pool)

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
