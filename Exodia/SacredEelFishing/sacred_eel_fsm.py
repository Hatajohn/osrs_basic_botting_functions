"""Question: How does the sacred eel fishing state machine advance each tick?

Building blocks (reused by this FSM, usable elsewhere):

- ``bot_wait.poll_until`` — generic timed polling
- ``bot_action_ui`` — action-strip codes, predicates, ``wait_for_action_code``
- ``bot_search`` — playspace ROI, ``search_with_camera_pan`` (+ optional walk relocate)
- ``bot_env`` — capture/input backends, ``send_camera_arrow``, ``camera_arrow_hold_ms``

Item labels (``items/<stem>.png`` via ``bot_inventory_items``):

- ``EEL_ITEM_NAME`` — default ``sacred_eel`` (``EXODIA_SACRED_EEL_ITEM``); eel slot count + scale target
- ``KNIFE_ITEM_NAME`` — default ``knife`` (``EXODIA_SACRED_KNIFE_ITEM``); knife source for scaling

States
------
FISHING     — Green action strip visible (code 0); poll only, never search for spots.
SEEK_SPOT   — Red NOT fishing strip (code 1); wait for it before clicking a new spot.
SCALING     — Inventory full or eel stack ready; knife → eel until no eels remain.

Scaling sub-phases (within SCALING)
------------------------------------
CLICK       — Click knife, then eel (``use_x_on_y`` with ``osrs_knife.png`` / ``osrs_sacredEel.png``).
WAIT_TICK   — Wait one game tick, refresh, re-count eels; loop or exit.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

import cv2
import bot_actions as Actions
import constants
from bot_action_ui import (
    ACTION_FISHING,
    ACTION_IDLE,
    ACTION_NO_UI,
    action_code_label,
    can_click_fishing_spot,
    describe_post_click_wait_status,
    is_action_fishing,
    is_action_idle,
    is_fishing_ui_visible,
    post_click_fish_poll_s,
    post_click_fish_wait_s,
    should_seek_fishing_spot,
    wait_for_action_code,
    wait_idle_before_spot_s,
)
from bot_search import search_with_camera_pan, walk_direction_for_attempt
from .sacred_eel_log import LOGS_DIR, ensure_logs_dir
from .sacred_eel_progress import InventoryProgressScore

if TYPE_CHECKING:
    import bot_arms as Arms
    import bot_client as Client
    import bot_eyes as Eyes

# Inventory template PNGs (images/) for use_x_on_y scaling fallback.
EEL_INV = "osrs_sacredEel.png"
KNIFE_INV = "osrs_knife.png"
# Named item label stems (items/<stem>.png) for read_inventory_labels / count_labeled_item_slots.
EEL_ITEM_NAME = os.environ.get("EXODIA_SACRED_EEL_ITEM", "sacred_eel")
KNIFE_ITEM_NAME = os.environ.get("EXODIA_SACRED_KNIFE_ITEM", "knife")
SPOT_TEMPLATES: list = []
FULL_EEL_COUNT = 22
INV_SLOT_COUNT = 28
MAX_SPOT_PAN_ATTEMPTS = 8
MAX_SPOT_WALK_ATTEMPTS = 4
SCALE_TICK_DELAY_S = constants.OSRS_TICK_S
MAX_SCALE_ACTIONS = 32
POST_CLICK_FISH_WAIT_S = 7.0
POST_CLICK_FISH_POLL_S = 0.75

def _noop_event(_event: str, **_fields: object) -> None:
    pass


def _noop_last_action(_msg: Optional[str]) -> None:
    pass


_sleep: Callable[[float], None] = time.sleep
_stop_check: Callable[[], bool] = lambda: False
_log_event: Callable[..., None] = _noop_event
_set_last_action: Callable[[Optional[str]], None] = _noop_last_action

# Perception helpers injected at runtime (avoids circular imports).
_count_eels: Callable = lambda _e: 0
_inv_slots: Callable = lambda _e: None
_inv_full: Callable = lambda _e: False
_locate_spots: Callable = lambda _e: []
def _inv_template_threshold() -> float:
    from bot_shape_match import inventory_template_threshold

    return inventory_template_threshold()


class SacredEelState(Enum):
    FISHING = auto()
    SEEK_SPOT = auto()
    SCALING = auto()


class ScalePhase(Enum):
    CLICK = auto()
    WAIT_TICK = auto()


@dataclass
class SacredEelContext:
    client: "Client.ClientWindow"
    bot_e: "Eyes.BotEyes"
    bot_a: "Arms.BotArms"
    state: SacredEelState = SacredEelState.SEEK_SPOT
    scale_phase: ScalePhase = ScalePhase.CLICK
    scale_actions: int = 0
    cycles: int = 0
    action_code: int = 2
    eel_count: int = 0
    inv_slots: Optional[int] = None
    waiting_for_fish: bool = False
    last_spot_click: Optional[list] = None
    progress: InventoryProgressScore = field(default_factory=InventoryProgressScore)
    # After the first spot click / fishing session, require red NOT fishing before re-clicking.
    need_red_before_spot: bool = False

    def refresh(self, *, record_progress: bool = False) -> None:
        """
        Capture + perception update.

        Stagnation scoring runs only when ``record_progress=True`` (once per FSM
        ``step()``), not during post-click waits or camera-pan polls.
        """
        Actions.bot_update(self.client, self.bot_e)
        self.action_code = self.bot_e.get_action_text(refresh=False)
        self.eel_count = _count_eels(self.bot_e)
        self.inv_slots = _inv_slots(self.bot_e)
        if record_progress:
            self._record_progress()

    def _record_progress(self) -> None:
        event = self.progress.observe(self.eel_count, self.inv_slots)
        _log_event(
            "progress.observe",
            progress_event=event,
            score=self.progress.score,
            stagnation_streak=self.progress.stagnation_streak,
            eel_count=self.eel_count,
            inv_slots=self.inv_slots,
        )
        if event == "stagnant":
            print(
                "STAGNATION: no progress for %d checks (eels=%d inv=%s score=%d)"
                % (
                    self.progress.stagnation_streak,
                    self.eel_count,
                    self.inv_slots if self.inv_slots is not None else "?",
                    self.progress.score,
                )
            )
        elif event == "fishing":
            print(
                "Progress +%d (fishing) → score %d | eels %d"
                % (self.progress.last_delta, self.progress.score, self.eel_count)
            )
        elif event == "scaling":
            print(
                "Progress +%d (scaling) → score %d | eels %d"
                % (-self.progress.last_delta, self.progress.score, self.eel_count)
            )
        elif event == "inv_change":
            print(
                "Progress +%d (inventory slots) → score %d | inv %s"
                % (abs(self.progress.last_delta), self.progress.score, self.inv_slots)
            )


def should_enter_scaling(ctx: SacredEelContext) -> bool:
    return _inv_full(ctx.bot_e) or ctx.eel_count >= FULL_EEL_COUNT


def _save_stagnation_snapshot(ctx: SacredEelContext) -> None:
    """Write last frame crops to logs/diag/ for post-mortem review."""
    try:
        ensure_logs_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = LOGS_DIR / "diag" / ("stop_%s" % stamp)
        out.mkdir(parents=True, exist_ok=True)
        if ctx.bot_e.curr_client is not None and ctx.bot_e.curr_client.size > 0:
            cv2.imwrite(str(out / "client.png"), ctx.bot_e.curr_client)
        if ctx.bot_e.curr_inventory is not None and ctx.bot_e.curr_inventory.size > 0:
            cv2.imwrite(str(out / "inventory.png"), ctx.bot_e.curr_inventory)
        strip = ctx.bot_e._action_strip_bgr()
        if strip is not None and strip.size > 0:
            cv2.imwrite(str(out / "action_strip.png"), strip)
        print("Saved stagnation snapshots ->", out)
    except Exception as exc:
        print("Could not save stagnation snapshot:", exc)


def _transition(ctx: SacredEelContext, new: SacredEelState, reason: str) -> SacredEelState:
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
    if new == SacredEelState.SCALING:
        ctx.scale_phase = ScalePhase.CLICK
        ctx.scale_actions = 0
    return new


def _after_scaling_done(ctx: SacredEelContext) -> SacredEelState:
    if is_action_fishing(ctx.action_code):
        return _transition(ctx, SacredEelState.FISHING, "scaled; green action line")
    if is_action_idle(ctx.action_code):
        return _transition(ctx, SacredEelState.SEEK_SPOT, "scaled; red action line — seek spot")
    return _transition(ctx, SacredEelState.SEEK_SPOT, "scaled; no fishing UI — seek spot")


class SacredEelMachine:
    """Question: How does one sacred eel FSM tick advance (fish / seek / scale)?

    One ``step()`` = one state action (or scaling sub-step). States: FISHING, SEEK_SPOT,
    SCALING (CLICK / WAIT_TICK). ``should_throttle()`` is True for FISHING and SEEK_SPOT
    so the outer loop polls on an interval; SCALING runs back-to-back until eels are gone.
    """

    def __init__(self, ctx: SacredEelContext):
        self.ctx = ctx

    def should_throttle(self) -> bool:
        """FISHING / SEEK_SPOT poll on the outer loop interval; SCALING runs back-to-back."""
        return self.ctx.state in (SacredEelState.FISHING, SacredEelState.SEEK_SPOT)

    def step(self) -> None:
        if _stop_check():
            return
        self.ctx.cycles += 1
        self.ctx.refresh(record_progress=True)

        if self.ctx.state == SacredEelState.FISHING:
            self._step_fishing()
        elif self.ctx.state == SacredEelState.SEEK_SPOT:
            self._step_seek_spot()
        elif self.ctx.state == SacredEelState.SCALING:
            self._step_scaling()

    def _step_fishing(self) -> None:
        ctx = self.ctx
        if should_enter_scaling(ctx):
            inv = ctx.inv_slots
            if inv is not None and inv >= INV_SLOT_COUNT:
                reason = "inventory full (%d/%d)" % (inv, INV_SLOT_COUNT)
            else:
                reason = "%d eels (>=%d)" % (ctx.eel_count, FULL_EEL_COUNT)
            _transition(ctx, SacredEelState.SCALING, reason)
            return

        if should_seek_fishing_spot(ctx.action_code):
            ctx.need_red_before_spot = True
            _transition(ctx, SacredEelState.SEEK_SPOT, "red NOT fishing UI — seek next spot")
            return

        if ctx.action_code == ACTION_NO_UI:
            print("Fishing (green UI hidden) — waiting for red NOT fishing before re-seeking")
            return

        if not is_action_fishing(ctx.action_code):
            print("Unexpected action code %d while fishing — waiting" % ctx.action_code)
            return

        # Green action line but no eels for many checks — wait for natural spot depletion (red UI).
        if (
            ctx.eel_count == 0
            and ctx.progress.stagnation_streak >= 4
            and is_action_fishing(ctx.action_code)
        ):
            print(
                "Fishing UI but no eels in inventory — waiting for red NOT fishing before re-seeking"
            )
            return

        print("Fishing (green action line)")

    def _step_seek_spot(self) -> None:
        ctx = self.ctx
        if should_enter_scaling(ctx):
            _transition(ctx, SacredEelState.SCALING, "need to scale before fishing")
            return

        if is_action_fishing(ctx.action_code):
            _transition(ctx, SacredEelState.FISHING, "green action line — already fishing")
            return

        if not self._wait_for_not_fishing_ui(ctx):
            return

        if not self._ready_to_search_spot(ctx):
            print(
                "Cannot click spot yet — need red NOT fishing UI (now: %s)"
                % action_code_label(ctx.action_code)
            )
            return

        if self._click_spot_with_pan(ctx):
            print("Clicked sacred eel spot")
            self._wait_for_fishing_start(ctx)
            return

        print(
            "No sacred eel spot found after %d camera pans and %d walk attempts (tried %s)"
            % (MAX_SPOT_PAN_ATTEMPTS, MAX_SPOT_WALK_ATTEMPTS, ", ".join(SPOT_TEMPLATES))
        )

    def _wait_for_fishing_start(self, ctx: SacredEelContext) -> bool:
        """After a spot click, poll until the green action strip appears."""
        wait_s = post_click_fish_wait_s(POST_CLICK_FISH_WAIT_S)
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        ctx.waiting_for_fish = True
        _set_last_action("wait_fishing start (%.0fs)" % wait_s)
        _log_event(
            "fsm.wait_fishing",
            phase="start",
            wait_s=wait_s,
            poll_s=poll_s,
        )
        print(
            "Waiting for fishing to start (up to %.0fs, poll every %.1fs)..."
            % (wait_s, poll_s)
        )

        def _read_code() -> int:
            ctx.refresh()
            return ctx.action_code

        result = wait_for_action_code(
            _read_code,
            is_action_fishing,
            timeout_s=wait_s,
            interval_s=poll_s,
            sleep_fn=_sleep,
            stop_check=_stop_check,
            on_status=lambda _n, code: describe_post_click_wait_status(code),
        )
        ctx.waiting_for_fish = False
        if result.success:
            _set_last_action("wait_fishing ok")
            _log_event(
                "fsm.wait_fishing",
                phase="end",
                success=True,
                action_code=ctx.action_code,
                cancelled=result.cancelled,
            )
            _transition(ctx, SacredEelState.FISHING, "green action line after spot click")
            return True
        if result.cancelled:
            _set_last_action("wait_fishing cancelled")
            _log_event(
                "fsm.wait_fishing",
                phase="end",
                success=False,
                action_code=ctx.action_code,
                cancelled=True,
            )
            return False
        _set_last_action("wait_fishing timeout")
        _log_event(
            "fsm.wait_fishing",
            phase="end",
            success=False,
            action_code=ctx.action_code,
            cancelled=False,
        )
        print(
            "Fishing did not start within %.0fs (%s) — wait for red NOT fishing before next spot"
            % (wait_s, action_code_label(ctx.action_code))
        )
        return False

    def _ready_to_search_spot(self, ctx: SacredEelContext) -> bool:
        """Red NOT fishing UI, or hidden strip before the first spot click of the session."""
        if can_click_fishing_spot(ctx.action_code):
            return True
        if ctx.action_code == ACTION_NO_UI and not ctx.need_red_before_spot:
            return True
        return False

    def _wait_for_not_fishing_ui(self, ctx: SacredEelContext) -> bool:
        """Block until the red NOT fishing strip appears (spot ready to click)."""
        if self._ready_to_search_spot(ctx):
            if ctx.action_code == ACTION_NO_UI and not ctx.need_red_before_spot:
                print("No action strip yet — searching for first spot click")
            return True

        wait_s = wait_idle_before_spot_s()
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        _set_last_action("wait_idle_before_spot (%.0fs)" % wait_s)
        _log_event("fsm.wait_idle", phase="start", wait_s=wait_s, poll_s=poll_s)
        print(
            "Waiting for red NOT fishing UI before spot click (up to %.0fs) — now %s"
            % (wait_s, action_code_label(ctx.action_code))
        )

        def _read_code() -> int:
            ctx.refresh(record_progress=False)
            return ctx.action_code

        def _on_poll(_n: int, code: int) -> None:
            if code == ACTION_NO_UI:
                print("  Action strip hidden — still waiting for red NOT fishing...")
            elif is_action_fishing(code):
                print("  Green fishing UI — still waiting for red NOT fishing...")

        result = wait_for_action_code(
            _read_code,
            can_click_fishing_spot,
            timeout_s=wait_s,
            interval_s=poll_s,
            sleep_fn=_sleep,
            stop_check=_stop_check,
            on_status=_on_poll,
        )
        if result.success:
            _set_last_action("wait_idle_before_spot ok")
            _log_event(
                "fsm.wait_idle",
                phase="end",
                success=True,
                action_code=ctx.action_code,
                cancelled=result.cancelled,
            )
            return True
        _set_last_action("wait_idle_before_spot timeout")
        _log_event(
            "fsm.wait_idle",
            phase="end",
            success=False,
            action_code=ctx.action_code,
            cancelled=result.cancelled,
        )
        print(
            "Red NOT fishing UI did not appear within %.0fs (%s)"
            % (wait_s, action_code_label(ctx.action_code))
        )
        return False

    def _click_spot_with_pan(self, ctx: SacredEelContext) -> bool:
        """Find/click a spot when red NOT fishing (or hidden strip before first cast)."""
        if is_action_fishing(ctx.action_code) or not self._ready_to_search_spot(ctx):
            return False

        def _locate() -> list:
            ctx.refresh(record_progress=False)
            if is_action_fishing(ctx.action_code):
                return []
            return _locate_spots(ctx.bot_e)

        def _pan() -> None:
            direction = "right" if random.random() > 0.5 else "left"
            _set_last_action("camera_pan %s" % direction)
            if direction == "right":
                ctx.bot_a.pan_right(
                    center=ctx.bot_e.global_center,
                    win_rect=ctx.bot_e.client_rect,
                    rand=True,
                )
            else:
                ctx.bot_a.pan_left(
                    center=ctx.bot_e.global_center,
                    win_rect=ctx.bot_e.client_rect,
                    rand=True,
                )

        rotate = os.environ.get("EXODIA_CAMERA_ROTATE", "keys")

        def _on_miss(attempt: int, max_attempts: int) -> None:
            _log_event(
                "input.camera_pan",
                rotate=rotate,
                attempt=attempt,
                max_attempts=max_attempts,
            )
            print(
                "No verified spot — rotating camera via %s (%d/%d)"
                % (rotate, attempt, max_attempts)
            )

        walk_wait_s = float(os.environ.get("EXODIA_WALK_WAIT_S", "3.0"))

        def _relocate(walk_i: int, max_walk: int) -> None:
            direction = walk_direction_for_attempt(walk_i - 1)
            _set_last_action("walk_click %s" % direction)
            _log_event(
                "input.walk_click",
                direction=direction,
                attempt=walk_i,
                max_attempts=max_walk,
            )
            print(
                "No spot after camera pans — walking %s (%d/%d)"
                % (direction, walk_i, max_walk)
            )
            ctx.bot_a.walk_direction(
                center=ctx.bot_e.global_center,
                win_rect=ctx.bot_e.client_rect,
                direction=direction,
            )

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
        )
        if not hits:
            return False
        print("Found %d verified sacred eel spot(s)" % len(hits))
        target = random.choice(hits)
        ctx.last_spot_click = list(target)
        _set_last_action("spot_click %s" % target)
        _log_event("fsm.spot_click", hit_count=len(hits), click_xy=target)
        ctx.need_red_before_spot = True
        ctx.bot_a.click_at(target, rad=11)
        return True

    def _step_scaling(self) -> None:
        ctx = self.ctx

        if ctx.eel_count == 0:
            print("Scaling complete — no sacred eels in inventory")
            _log_event("fsm.scaling", phase="complete", eel_count=0)
            _after_scaling_done(ctx)
            return

        if ctx.scale_phase == ScalePhase.CLICK:
            self._scale_click()
        elif ctx.scale_phase == ScalePhase.WAIT_TICK:
            self._scale_wait_tick()

    def _scale_click(self) -> None:
        ctx = self.ctx
        if ctx.scale_actions >= MAX_SCALE_ACTIONS:
            print("Scaling safety cap (%d actions)" % MAX_SCALE_ACTIONS)
            _after_scaling_done(ctx)
            return

        print("Scaling: knife → eel (%d eel icon(s))" % ctx.eel_count)
        _log_event(
            "fsm.scaling",
            phase="click",
            eel_count=ctx.eel_count,
            scale_actions=ctx.scale_actions,
        )
        _set_last_action("scaling knife→eel")
        result = Actions.use_x_on_y(
            ctx.bot_e,
            ctx.bot_a,
            KNIFE_INV,
            EEL_INV,
            threshold=_inv_template_threshold(),
        )
        if not result.ok:
            print(
                "Scaling failed — %s (%s)"
                % (result.reason, result.missing_item or "unknown")
            )
            _after_scaling_done(ctx)
            return

        ctx.scale_actions += 1
        ctx.scale_phase = ScalePhase.WAIT_TICK

    def _scale_wait_tick(self) -> None:
        ctx = self.ctx
        _set_last_action("scaling tick wait")
        _sleep(SCALE_TICK_DELAY_S)
        ctx.refresh(record_progress=True)
        remaining = ctx.eel_count
        print("  After tick wait: %d eel icon(s) remaining" % remaining)
        _log_event(
            "fsm.scaling",
            phase="wait_tick",
            eel_count=remaining,
            scale_actions=ctx.scale_actions,
        )

        if remaining == 0:
            print("Scaling complete — no sacred eels left")
            _log_event("fsm.scaling", phase="complete", eel_count=0)
            _after_scaling_done(ctx)
            return

        ctx.scale_phase = ScalePhase.CLICK


def configure_fsm(
    *,
    sleep_fn: Callable[[float], None],
    stop_check: Callable[[], bool],
    count_eels: Callable,
    inv_slots: Callable,
    inv_full: Callable,
    locate_spots: Callable,
    spot_templates: list,
    full_eel_count: int,
    inv_slot_count: int,
    max_spot_pan_attempts: int,
    max_spot_walk_attempts: int = 4,
    scale_tick_delay_s: float,
    max_scale_actions: int,
    post_click_fish_wait_s: float = POST_CLICK_FISH_WAIT_S,
    post_click_fish_poll_s: float = POST_CLICK_FISH_POLL_S,
    log_event: Callable[..., None] = _noop_event,
    set_last_action: Callable[[Optional[str]], None] = _noop_last_action,
) -> None:
    """Wire module-level hooks from ``sacred_eel_fishing`` (called once at startup)."""
    global _sleep, _stop_check, _count_eels, _inv_slots, _inv_full
    global _locate_spots, SPOT_TEMPLATES
    global FULL_EEL_COUNT, INV_SLOT_COUNT, MAX_SPOT_PAN_ATTEMPTS, MAX_SPOT_WALK_ATTEMPTS
    global SCALE_TICK_DELAY_S, MAX_SCALE_ACTIONS
    global POST_CLICK_FISH_WAIT_S, POST_CLICK_FISH_POLL_S
    global _log_event, _set_last_action

    _sleep = sleep_fn
    _stop_check = stop_check
    _count_eels = count_eels
    _inv_slots = inv_slots
    _inv_full = inv_full
    _locate_spots = locate_spots
    SPOT_TEMPLATES = spot_templates
    FULL_EEL_COUNT = full_eel_count
    INV_SLOT_COUNT = inv_slot_count
    MAX_SPOT_PAN_ATTEMPTS = max_spot_pan_attempts
    MAX_SPOT_WALK_ATTEMPTS = max(0, int(max_spot_walk_attempts))
    SCALE_TICK_DELAY_S = scale_tick_delay_s
    MAX_SCALE_ACTIONS = max_scale_actions
    POST_CLICK_FISH_WAIT_S = post_click_fish_wait_s
    POST_CLICK_FISH_POLL_S = post_click_fish_poll_s
    _log_event = log_event
    _set_last_action = set_last_action
