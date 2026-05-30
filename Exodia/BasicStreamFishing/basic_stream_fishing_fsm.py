"""
Basic stream fishing FSM — FISHING and SEEK_SPOT on ``StreamBotContext`` only.

No ``BotEyes`` / ``bot_update``; spots come from stable world tracks on the
perception stream. Action state is read from on-screen ``Fishing`` / ``Not fishing``
text (``perception.text``) via ``resolve_fishing_action_from_tick``, with stream
``perception.action`` as fallback.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional, Sequence, Tuple

from bot_action_ui import (
    ACTION_FISHING,
    ACTION_IDLE,
    ACTION_NO_UI,
    action_code_label,
    can_seek_fishing_spot,
    describe_post_click_wait_status,
    is_action_fishing,
    post_click_fish_poll_s,
    post_click_fish_wait_s,
    should_seek_fishing_spot,
    wait_for_action_code,
    wait_idle_before_spot_s,
)
from bot_perception_events import PerceptionEvent
from bot_perception_types import PerceptionTick
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


@dataclass
class BasicStreamFishingContext:
    """Stream session state for basic fishing (no inventory/cracking)."""

    stream: StreamBotContext
    state: BasicStreamFishingState = BasicStreamFishingState.SEEK_SPOT
    cycles: int = 0
    action_code: int = ACTION_NO_UI
    action_line_text: Optional[str] = None
    action_line_color: Optional[str] = None
    action_detection_source: Optional[str] = None
    waiting_for_fish: bool = False
    need_red_before_spot: bool = False
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
        if _BASIC_FISHING_DEBUG:
            text = tick.text
            action = tick.action
            print(
                "FishingDBG: spans=%d meta_count=%d text_seq=%d action_seq=%d "
                "stream_code=%d resolved=%d src=%s line=%r strip=%s"
                % (
                    len(text.spans),
                    text.span_count,
                    text.seq,
                    action.seq,
                    action.action_code,
                    self.action_code,
                    self.action_detection_source,
                    self.action_line_text,
                    action.action_strip_rect,
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


def _spot_hit_count(tick: Optional[PerceptionTick]) -> int:
    if tick is None:
        return 0
    return len(_locate_spots_from_tick(tick))


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
    return new


class BasicStreamFishingMachine:
    """One ``step()`` = one FISHING or SEEK_SPOT action (stream poll path only)."""

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

        if self.ctx.state == BasicStreamFishingState.FISHING:
            self._step_fishing()
        elif self.ctx.state == BasicStreamFishingState.SEEK_SPOT:
            self._step_seek_spot()

    def _step_fishing(self) -> None:
        ctx = self.ctx
        if should_seek_fishing_spot(ctx.action_code):
            ctx.need_red_before_spot = True
            _transition(
                ctx,
                BasicStreamFishingState.SEEK_SPOT,
                "Not fishing text — seek next spot",
            )
            return

        if ctx.action_code == ACTION_NO_UI:
            spot_n = _spot_hit_count(ctx.last_tick)
            if spot_n > 0:
                ctx.need_red_before_spot = False
                _transition(
                    ctx,
                    BasicStreamFishingState.SEEK_SPOT,
                    "green UI hidden with %d spot track(s) — re-seek" % spot_n,
                )
                return
            print(
                "%s (strip hidden) — waiting for Not fishing before re-seeking"
                % fishing_action_label(ACTION_FISHING)
            )
            return

        if not is_action_fishing(ctx.action_code):
            print(
                "Unexpected state %s while fishing — waiting"
                % ctx.action_status_label()
            )
            return

        print("Fishing — %s" % ctx.action_status_label())

    def _step_seek_spot(self) -> None:
        ctx = self.ctx
        if is_action_fishing(ctx.action_code):
            _transition(
                ctx,
                BasicStreamFishingState.FISHING,
                "green action line — already fishing",
            )
            ctx.need_red_before_spot = True
            return

        if not self._wait_for_seek_gate(ctx):
            return

        if not can_seek_fishing_spot(
            ctx.action_code, need_red_before_spot=ctx.need_red_before_spot
        ):
            spot_n = _spot_hit_count(ctx.last_tick)
            print(
                "Cannot click spot yet — need red NOT fishing UI (now: %s, %d track(s) visible)"
                % (action_code_label(ctx.action_code), spot_n)
            )
            return

        if self._click_spot_with_pan(ctx):
            print("Clicked infernal eel spot (stream track)")
            self._wait_for_fishing_start(ctx)
            return

        print(
            "No infernal eel spot found after %d camera pans and %d walk attempts (stems: %s)"
            % (
                MAX_SPOT_PAN_ATTEMPTS,
                MAX_SPOT_WALK_ATTEMPTS,
                ", ".join(_spot_stems()),
            )
        )

    def _wait_for_fishing_start(self, ctx: BasicStreamFishingContext) -> bool:
        wait_s = post_click_fish_wait_s(POST_CLICK_FISH_WAIT_S)
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        ctx.waiting_for_fish = True
        _set_last_action("wait_fishing start (%.0fs)" % wait_s)
        _log_event("fsm.wait_fishing", phase="start", wait_s=wait_s, poll_s=poll_s)
        print(
            "Waiting for fishing to start (up to %.0fs, poll every %.1fs)..."
            % (wait_s, poll_s)
        )

        ctx.refresh()
        if is_action_fishing(ctx.action_code):
            ctx.waiting_for_fish = False
            ctx.need_red_before_spot = True
            _set_last_action("wait_fishing ok (already green)")
            _transition(
                ctx,
                BasicStreamFishingState.FISHING,
                "green action line after spot click",
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
            ctx.need_red_before_spot = True
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
                "green action line after spot click",
            )
            return True
        if result.cancelled:
            _set_last_action("wait_fishing cancelled")
            return False
        ctx.refresh()
        _set_last_action("wait_fishing timeout")
        if not is_action_fishing(ctx.action_code):
            ctx.need_red_before_spot = False
            print(
                "Fishing did not start within %.0fs (%s) — allow re-seek (NOT fishing UI not required)"
                % (wait_s, action_code_label(ctx.action_code))
            )
        else:
            print(
                "Fishing did not start within %.0fs (%s) — wait for red NOT fishing before next spot"
                % (wait_s, action_code_label(ctx.action_code))
            )
        return False

    def _wait_for_seek_gate(self, ctx: BasicStreamFishingContext) -> bool:
        if can_seek_fishing_spot(
            ctx.action_code, need_red_before_spot=ctx.need_red_before_spot
        ):
            if ctx.action_code == ACTION_NO_UI and not ctx.need_red_before_spot:
                print("No action strip yet — searching for first spot click")
            return True

        wait_s = wait_idle_before_spot_s()
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        _set_last_action("wait_idle_before_spot (%.0fs)" % wait_s)
        print(
            "Waiting for red NOT fishing UI before spot click (up to %.0fs) — now %s"
            % (wait_s, ctx.action_status_label())
        )

        def _read_code() -> int:
            ctx.refresh()
            return ctx.action_code

        result = wait_for_action_code(
            _read_code,
            lambda code: can_seek_fishing_spot(
                code, need_red_before_spot=ctx.need_red_before_spot
            ),
            timeout_s=wait_s,
            interval_s=poll_s,
            sleep_fn=_sleep,
            stop_check=_stop_check,
        )
        if not result.success:
            spot_n = _spot_hit_count(ctx.last_tick)
            if (
                spot_n > 0
                and not is_action_fishing(ctx.action_code)
                and ctx.action_code != ACTION_IDLE
            ):
                print(
                    "NOT fishing UI did not appear within %.0fs — seeking via %d visible track(s)"
                    % (wait_s, spot_n)
                )
                ctx.need_red_before_spot = False
                return True
            print(
                "NOT fishing UI did not appear within %.0fs (code %s) — not idle-at-spot yet"
                % (wait_s, action_code_label(ctx.action_code))
            )
        return result.success

    def _click_spot_with_pan(self, ctx: BasicStreamFishingContext) -> bool:
        if is_action_fishing(ctx.action_code) or not can_seek_fishing_spot(
            ctx.action_code, need_red_before_spot=ctx.need_red_before_spot
        ):
            return False

        center = ctx.global_center()
        rect = ctx.client_rect()
        if center is None or rect is None:
            print("No client rect — cannot pan or click spot")
            return False

        arms = ctx.stream.arms

        def _locate() -> List[List[int]]:
            tick, _ = ctx.refresh()
            if is_action_fishing(tick.action.action_code):
                return []
            return _locate_spots_from_tick(tick)

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
            relocate=_relocate if MAX_SPOT_WALK_ATTEMPTS > 0 else None,
            max_relocate_attempts=MAX_SPOT_WALK_ATTEMPTS,
            sleep_after_relocate_s=walk_wait_s,
            signal_pan=stream_pan_signal(),
        )
        if not hits:
            return False
        print("Found %d infernal spot hit(s) from stream tracks" % len(hits))
        target = random.choice(hits)
        ctx.last_spot_click = list(target)
        _set_last_action("spot_click %s" % target)
        _log_event("fsm.spot_click", hit_count=len(hits), click_xy=target)
        ctx.need_red_before_spot = True
        arms.click_at(target, rad=11)
        return True


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
    "configure_fsm",
    "initial_state_from_action",
]
