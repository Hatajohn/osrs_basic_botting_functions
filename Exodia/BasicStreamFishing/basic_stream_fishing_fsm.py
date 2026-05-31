"""
Basic stream fishing FSM — FISHING, SEEK_SPOT, and CRACKING on ``StreamBotContext``.

Signals (no ``BotEyes``):
- **Fishing?** — green ``Fishing`` in ``tick.text`` via ``resolve_fishing_action_from_tick``.
- **Spots** — stable world template tracks (infernal eel stems).
- **Full inventory** — ``empty_slot_count() == 0`` (no free slots) → CRACKING.
- **Crack done** — empty slot count unchanged for ``CRACK_EMPTY_STABLE_S`` after the hammer click → seek/fish again.

Loop: seek → click spot → wait green → fish → full (0 empty) → crack → free slot → seek.

Green ``Fishing`` in ``tick.text`` while in SEEK_SPOT → FISHING immediately (including
mid camera pan); no spot click when already skilling.

TODO: Extract cracking (one hammer click, poll-until-target, slot grid) into
``BasicStreamFishing/basic_stream_cracking.py`` or shared ``bot_stream_cracking.py``
when a second bot needs it.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional, Sequence, Tuple

from bot_action_ui import (
    ACTION_NO_UI,
    action_code_label,
    describe_post_click_wait_status,
    is_action_fishing,
    post_click_fish_poll_s,
    post_click_fish_wait_s,
    wait_for_action_code,
)
from bot_inventory_actions import use_named_item_on_named_item
from bot_perception_events import PerceptionEvent
from bot_perception_types import (
    INV_SLOT_COUNT,
    InventorySlotCountError,
    InventorySnapshot,
    PerceptionTick,
)
from bot_text_query import (
    fishing_action_label,
    resolve_fishing_action_from_tick,
)
from bot_playspace import global_center_from_client_rect
from bot_search import search_with_camera_pan, walk_direction_for_attempt
from bot_stream_context import StreamBotContext
from bot_stream_control import infernal_spot_world_stems, stream_pan_signal

MAX_SPOT_PAN_ATTEMPTS = int(os.environ.get("EXODIA_SPOT_PAN_ATTEMPTS", "8"))
MAX_SPOT_WALK_ATTEMPTS = int(os.environ.get("EXODIA_SPOT_WALK_ATTEMPTS", "4"))
POST_CLICK_FISH_WAIT_S = float(os.environ.get("EXODIA_POST_CLICK_FISH_WAIT_S", "7"))
POST_CLICK_FISH_POLL_S = float(os.environ.get("EXODIA_POST_CLICK_FISH_POLL_S", "0.75"))
INV_FULL_DEBOUNCE = max(1, int(os.environ.get("EXODIA_INV_FULL_DEBOUNCE", "2")))
CRACK_EMPTY_STABLE_S = float(os.environ.get("EXODIA_CRACK_EMPTY_STABLE_S", "5.0"))
EEL_ITEM = os.environ.get("EXODIA_INFERNAL_EEL_ITEM", "infernal_eel")
HAMMER_ITEM = os.environ.get("EXODIA_INFERNAL_HAMMER_ITEM", "hammer")
NOT_FISHING_DEBOUNCE = max(1, int(os.environ.get("EXODIA_NOT_FISHING_DEBOUNCE", "2")))
_BASIC_FISHING_DEBUG = os.environ.get("EXODIA_BASIC_FISHING_DEBUG", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _noop_event(_event: str, **_fields: object) -> None:
    pass


def _noop_last_action(_msg: Optional[str]) -> None:
    pass


_sleep: Callable[[float], None] = time.sleep
_stop_check: Callable[[], bool] = lambda: False
_log_event: Callable[..., None] = _noop_event
_set_last_action: Callable[[Optional[str]], None] = _noop_last_action


class BasicStreamFishingState(Enum):
    FISHING = auto()
    SEEK_SPOT = auto()
    CRACKING = auto()


@dataclass
class BasicStreamFishingContext:
    """Stream session state for basic infernal eel fishing."""

    stream: StreamBotContext
    state: BasicStreamFishingState = BasicStreamFishingState.SEEK_SPOT
    cycles: int = 0
    action_code: int = ACTION_NO_UI
    action_line_text: Optional[str] = None
    action_line_color: Optional[str] = None
    action_detection_source: Optional[str] = None
    waiting_for_fish: bool = False
    crack_started: bool = False
    not_fishing_streak: int = 0
    crack_enter_streak: int = 0
    crack_last_empty: Optional[int] = None
    crack_empty_stable_since: Optional[float] = None
    last_spot_click: Optional[List[int]] = None
    last_tick: Optional[PerceptionTick] = None
    last_events: List[PerceptionEvent] = field(default_factory=list)

    def refresh(self) -> Tuple[PerceptionTick, List[PerceptionEvent]]:
        tick, events = self.stream.refresh()
        self.last_tick = tick
        self.last_events = list(events)
        inference = resolve_fishing_action_from_tick(tick)
        self.action_code = int(inference.action_code)
        self.action_line_text = inference.action_line_text
        self.action_line_color = inference.action_line_color
        self.action_detection_source = inference.detection_source
        tick.inventory.validate_slot_counts()
        if _BASIC_FISHING_DEBUG:
            text = tick.text
            print(
                "FishingDBG: spans=%d text_seq=%d resolved=%d src=%s line=%r"
                % (
                    len(text.spans),
                    text.seq,
                    self.action_code,
                    self.action_detection_source,
                    self.action_line_text,
                )
            )
        return tick, events

    def action_status_label(self) -> str:
        """Human-readable fishing UI state from OCR text when available."""
        if self.action_line_text:
            return "%s (%s)" % (
                fishing_action_label(self.action_code),
                self.action_line_text,
            )
        return action_code_label(self.action_code)

    def client_rect(self) -> Optional[Tuple[int, int, int, int]]:
        if self.last_tick is not None and self.last_tick.client_rect is not None:
            return self.last_tick.client_rect
        self.stream.client.update()
        rect = self.stream.client.client_rect
        return tuple(rect) if rect is not None else None

    def global_center(self) -> Optional[Tuple[int, int]]:
        rect = self.client_rect()
        if rect is None:
            return None
        return global_center_from_client_rect(rect)


def initial_state_from_action(action_code: int) -> BasicStreamFishingState:
    if is_action_fishing(action_code):
        return BasicStreamFishingState.FISHING
    return BasicStreamFishingState.SEEK_SPOT


def _spot_stems() -> List[str]:
    stems = infernal_spot_world_stems()
    return stems if stems else ["osrs_infernalEel"]


def _locate_spots_from_tick(tick: PerceptionTick) -> List[List[int]]:
    """Screen click points from stable tracks (fallback: best track per stem)."""
    hits: List[List[int]] = []
    world = tick.world
    for stem in _spot_stems():
        stable = world.stable_tracks(stem)
        if stable:
            for track in stable:
                hits.append([int(track.screen_xy[0]), int(track.screen_xy[1])])
            continue
        track = world.best_track(stem)
        if track is not None:
            hits.append([int(track.screen_xy[0]), int(track.screen_xy[1])])
    return hits


def _transition(
    ctx: BasicStreamFishingContext,
    new: BasicStreamFishingState,
    reason: str,
) -> BasicStreamFishingState:
    old = ctx.state
    if new != old:
        print("State: %s → %s (%s)" % (old.name, new.name, reason))
        _log_event(
            "fsm.transition",
            from_state=old.name,
            to_state=new.name,
            reason=reason,
        )
    ctx.state = new
    if new == BasicStreamFishingState.CRACKING:
        ctx.crack_started = False
        ctx.crack_enter_streak = 0
        ctx.crack_last_empty = None
        ctx.crack_empty_stable_since = None
    if new == BasicStreamFishingState.FISHING:
        ctx.not_fishing_streak = 0
    return new


def _reset_crack_empty_tracking(ctx: BasicStreamFishingContext, empty: int) -> None:
    ctx.crack_last_empty = empty
    ctx.crack_empty_stable_since = time.monotonic()


def _crack_empty_stable_s(ctx: BasicStreamFishingContext, empty: int) -> float:
    """Seconds the empty-slot count has been unchanged (resets on each change)."""
    if ctx.crack_last_empty is None or ctx.crack_empty_stable_since is None:
        _reset_crack_empty_tracking(ctx, empty)
        return 0.0
    if empty != ctx.crack_last_empty:
        _reset_crack_empty_tracking(ctx, empty)
        return 0.0
    return time.monotonic() - ctx.crack_empty_stable_since


def _exit_cracking(ctx: BasicStreamFishingContext, *, empty: int, stable_s: float) -> None:
    reason = "cracking done — %d empty slot(s) stable %.1fs" % (empty, stable_s)
    if is_action_fishing(ctx.action_code):
        _transition(ctx, BasicStreamFishingState.FISHING, reason)
    else:
        _transition(ctx, BasicStreamFishingState.SEEK_SPOT, reason)


def _maybe_enter_fishing_from_seek(ctx: BasicStreamFishingContext) -> bool:
    """Green Fishing text while seeking → FISHING immediately (poll for fish)."""
    if ctx.state != BasicStreamFishingState.SEEK_SPOT:
        return False
    if not is_action_fishing(ctx.action_code):
        return False
    _transition(ctx, BasicStreamFishingState.FISHING, "green Fishing text — wait for fish")
    return True


class BasicStreamFishingMachine:
    """
    One ``step()`` advances FISHING, SEEK_SPOT, or CRACKING.

    Closed loop: seek spot → click → wait for green text → fish until full (0 empty) →
    one hammer→eel → poll until empty count stops changing → seek again.
    """

    def __init__(self, ctx: BasicStreamFishingContext):
        self.ctx = ctx

    def should_throttle(self) -> bool:
        return self.ctx.state in (
            BasicStreamFishingState.FISHING,
            BasicStreamFishingState.SEEK_SPOT,
        )

    def step(self) -> None:
        if _stop_check():
            return
        self.ctx.cycles += 1
        self.ctx.refresh()

        # Early: green Fishing text overrides SEEK_SPOT before pan/click this tick.
        _maybe_enter_fishing_from_seek(self.ctx)

        if self.ctx.state == BasicStreamFishingState.FISHING:
            self._step_fishing()
        elif self.ctx.state == BasicStreamFishingState.SEEK_SPOT:
            self._step_seek_spot()
            if self.ctx.state == BasicStreamFishingState.FISHING:
                self._step_fishing()
        elif self.ctx.state == BasicStreamFishingState.CRACKING:
            self._step_cracking()

    def _maybe_enter_cracking(self, ctx: BasicStreamFishingContext) -> bool:
        tick = ctx.last_tick
        if tick is None:
            ctx.crack_enter_streak = 0
            return False
        inv = tick.inventory
        empty = inv.empty_slot_count()
        if empty > 0:
            ctx.crack_enter_streak = 0
            return False
        ctx.crack_enter_streak += 1
        if ctx.crack_enter_streak < INV_FULL_DEBOUNCE:
            if _BASIC_FISHING_DEBUG:
                print(
                    "Inventory full debounce %d/%d — %d empty, %d/%d occupied (grid)"
                    % (
                        ctx.crack_enter_streak,
                        INV_FULL_DEBOUNCE,
                        empty,
                        inv.occupied_from_grid(),
                        INV_SLOT_COUNT,
                    )
                )
            return False
        ctx.crack_enter_streak = 0
        _transition(
            ctx,
            BasicStreamFishingState.CRACKING,
            "inventory full (0 empty, %d/%d occupied)"
            % (inv.occupied_from_grid(), INV_SLOT_COUNT),
        )
        return True

    def _step_fishing(self) -> None:
        """Poll while green Fishing text is visible; leave on not-green or full inv."""
        ctx = self.ctx
        if self._maybe_enter_cracking(ctx):
            return
        if is_action_fishing(ctx.action_code):
            ctx.not_fishing_streak = 0
            print("Fishing — %s" % ctx.action_status_label())
            return
        ctx.not_fishing_streak += 1
        if ctx.not_fishing_streak < NOT_FISHING_DEBOUNCE:
            print(
                "Green Fishing not seen (%d/%d debounce) — %s"
                % (
                    ctx.not_fishing_streak,
                    NOT_FISHING_DEBOUNCE,
                    ctx.action_detection_source or "?",
                )
            )
            return
        ctx.not_fishing_streak = 0
        _transition(
            ctx,
            BasicStreamFishingState.SEEK_SPOT,
            "no green Fishing text — seek spot",
        )

    def _step_seek_spot(self) -> None:
        """Find and click a spot template when not fishing."""
        ctx = self.ctx
        if self._maybe_enter_cracking(ctx):
            return

        if self._click_spot_with_pan(ctx):
            print("Clicked infernal eel spot (stream track)")
            self._wait_for_fishing_start(ctx)
            return

        if ctx.state == BasicStreamFishingState.FISHING:
            return

        print(
            "No infernal eel spot found after %d camera pans and %d walk attempts (stems: %s)"
            % (
                MAX_SPOT_PAN_ATTEMPTS,
                MAX_SPOT_WALK_ATTEMPTS,
                ", ".join(_spot_stems()),
            )
        )

    def _step_cracking(self) -> None:
        """
        One hammer→eel click, then poll until empty-slot count stops changing.

        The game processes eels over time after the single use-on click; we exit once
        the number of free slots has been stable for ``CRACK_EMPTY_STABLE_S``.
        """
        ctx = self.ctx
        tick = ctx.last_tick
        if tick is None:
            return

        inv = tick.inventory
        empty = inv.empty_slot_count()

        if not ctx.crack_started:
            self._crack_click_once(ctx, tick, inv)
            _reset_crack_empty_tracking(ctx, empty)
            return

        stable_s = _crack_empty_stable_s(ctx, empty)
        if empty > 0 and stable_s >= CRACK_EMPTY_STABLE_S:
            _exit_cracking(ctx, empty=empty, stable_s=stable_s)
            return

        print(
            "Cracking — %d empty, %d/%d occupied (grid), stable %.1fs / %.1fs"
            % (
                empty,
                inv.occupied_from_grid(),
                INV_SLOT_COUNT,
                stable_s,
                CRACK_EMPTY_STABLE_S,
            )
        )

    def _crack_click_once(
        self,
        ctx: BasicStreamFishingContext,
        tick: PerceptionTick,
        inv: InventorySnapshot,
    ) -> None:
        inv_rect = inv.rect
        client_rect = tick.client_rect
        if inv_rect is None or client_rect is None:
            print("Cracking: missing inventory or client rect — waiting")
            ctx.crack_started = True
            return

        slot_items = _slot_items_from_inventory(inv)
        _set_last_action("cracking hammer→eel")
        print("Cracking: %s → %s (one click; game processes eels over time)" % (HAMMER_ITEM, EEL_ITEM))
        _log_event(
            "fsm.cracking",
            phase="click",
            occupied=inv.occupied,
            eel_slots=inv.count_label(EEL_ITEM),
        )
        result = use_named_item_on_named_item(
            inv_rect,
            client_rect,
            slot_items,
            HAMMER_ITEM,
            EEL_ITEM,
            arms=ctx.stream.arms,
        )
        ctx.crack_started = True
        if not result.ok:
            print(
                "Cracking failed — %s (%s)"
                % (result.reason, result.missing_item or "unknown")
            )
            _log_event("fsm.cracking", phase="click_failed", reason=result.reason)

    def _wait_for_fishing_start(self, ctx: BasicStreamFishingContext) -> bool:
        wait_s = post_click_fish_wait_s(POST_CLICK_FISH_WAIT_S)
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        ctx.waiting_for_fish = True
        _set_last_action("wait_fishing start (%.0fs)" % wait_s)
        _log_event("fsm.wait_fishing", phase="start", wait_s=wait_s, poll_s=poll_s)
        print(
            "Waiting for green Fishing text (up to %.0fs, poll every %.1fs)..."
            % (wait_s, poll_s)
        )

        ctx.refresh()
        if is_action_fishing(ctx.action_code):
            ctx.waiting_for_fish = False
            _set_last_action("wait_fishing ok (already green)")
            _transition(
                ctx,
                BasicStreamFishingState.FISHING,
                "green Fishing text after spot click",
            )
            return True

        def _read_code() -> int:
            ctx.refresh()
            return ctx.action_code

        def _on_status(_poll_n: int, code: int) -> Optional[str]:
            msg = describe_post_click_wait_status(code)
            if msg and ctx.action_line_text:
                return "%s (read: %r)" % (msg, ctx.action_line_text)
            return msg

        result = wait_for_action_code(
            _read_code,
            is_action_fishing,
            timeout_s=wait_s,
            interval_s=poll_s,
            sleep_fn=_sleep,
            stop_check=_stop_check,
            on_status=_on_status,
        )
        ctx.waiting_for_fish = False
        if result.success:
            ctx.refresh()
            _set_last_action("wait_fishing ok")
            _log_event(
                "fsm.wait_fishing",
                phase="end",
                success=True,
                action_code=ctx.action_code,
                cancelled=result.cancelled,
            )
            _transition(
                ctx,
                BasicStreamFishingState.FISHING,
                "green Fishing text after spot click",
            )
            return True
        if result.cancelled:
            _set_last_action("wait_fishing cancelled")
            return False
        ctx.refresh()
        _set_last_action("wait_fishing timeout")
        print(
            "Green Fishing text did not appear within %.0fs (%s) — will re-seek"
            % (wait_s, ctx.action_status_label())
        )
        return False

    def _click_spot_with_pan(self, ctx: BasicStreamFishingContext) -> bool:
        if is_action_fishing(ctx.action_code):
            return False

        center = ctx.global_center()
        rect = ctx.client_rect()
        if center is None or rect is None:
            print("No client rect — cannot pan or click spot")
            return False

        arms = ctx.stream.arms

        def _locate() -> List[List[int]]:
            tick, _ = ctx.refresh()
            if is_action_fishing(ctx.action_code):
                return []
            return _locate_spots_from_tick(tick)

        def _should_abort_seek() -> bool:
            ctx.refresh()
            return is_action_fishing(ctx.action_code)

        def _pan() -> None:
            direction = "right" if random.random() > 0.5 else "left"
            _set_last_action("camera_pan %s" % direction)
            if direction == "right":
                arms.pan_right(center=center, win_rect=rect, rand=True)
            else:
                arms.pan_left(center=center, win_rect=rect, rand=True)

        def _on_miss(attempt: int, max_attempts: int) -> None:
            print("No spot — rotating camera (%d/%d)" % (attempt, max_attempts))

        walk_wait_s = float(os.environ.get("EXODIA_WALK_WAIT_S", "3.0"))

        def _relocate(walk_i: int, max_walk: int) -> None:
            direction = walk_direction_for_attempt(walk_i - 1)
            _set_last_action("walk_click %s" % direction)
            print(
                "No spot after camera pans — walking %s (%d/%d)"
                % (direction, walk_i, max_walk)
            )
            arms.walk_direction(center=center, win_rect=rect, direction=direction)

        hits = search_with_camera_pan(
            _locate,
            _pan,
            max_pan_attempts=MAX_SPOT_PAN_ATTEMPTS,
            sleep_after_pan_s=random.uniform(0.4, 0.8),
            sleep_fn=_sleep,
            on_miss=_on_miss,
            should_abort=_should_abort_seek,
            relocate=_relocate if MAX_SPOT_WALK_ATTEMPTS > 0 else None,
            max_relocate_attempts=MAX_SPOT_WALK_ATTEMPTS,
            sleep_after_relocate_s=walk_wait_s,
            signal_pan=stream_pan_signal(),
        )
        if _maybe_enter_fishing_from_seek(ctx):
            return False
        if not hits:
            return False
        print("Found %d infernal spot hit(s) from stream tracks" % len(hits))
        target = random.choice(hits)
        ctx.last_spot_click = list(target)
        _set_last_action("spot_click %s" % target)
        _log_event("fsm.spot_click", hit_count=len(hits), click_xy=target)
        arms.click_at(target, rad=11)
        return True


# TODO: Move to BasicStreamFishing/basic_stream_cracking.py (or bot_stream_cracking.py)
# when a second consumer needs hammer→eel cracking on the stream inventory cache.


def _slot_items_from_inventory(inv: InventorySnapshot) -> List[List[Optional[str]]]:
    from bot_eyes import INV_COLS, INV_ROWS

    grid: List[List[Optional[str]]] = [[None] * INV_COLS for _ in range(INV_ROWS)]
    for slot in inv.slots:
        if slot.row < INV_ROWS and slot.col < INV_COLS and slot.occupied:
            grid[slot.row][slot.col] = slot.label
    return grid


def configure_fsm(
    *,
    sleep_fn: Callable[[float], None],
    stop_check: Callable[[], bool],
    log_event: Callable[..., None] = _noop_event,
    set_last_action: Callable[[Optional[str]], None] = _noop_last_action,
) -> None:
    """Wire runtime hooks (sleep, stop, logging) once at startup."""
    global _sleep, _stop_check, _log_event, _set_last_action
    _sleep = sleep_fn
    _stop_check = stop_check
    _log_event = log_event
    _set_last_action = set_last_action


__all__ = [
    "BasicStreamFishingContext",
    "BasicStreamFishingMachine",
    "BasicStreamFishingState",
    "InventorySlotCountError",
    "configure_fsm",
    "initial_state_from_action",
]
