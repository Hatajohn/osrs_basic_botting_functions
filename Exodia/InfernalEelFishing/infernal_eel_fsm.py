"""
Infernal eel FSM: when to fish, seek spots, or crack eels at full inventory.

Use this when you need state transitions for infernal eel fishing (not the session loop).

States
------
FISHING     — Green action strip (code 0); poll only.
SEEK_SPOT   — Red NOT fishing strip (code 1); find and click spot.
CRACKING    — Inventory full (28/28); hammer → eel until no eel slots remain.

Cracking sub-phases
-------------------
CLICK       — use hammer on eel (named items or template fallback).
WAIT_TICK   — Wait one game tick, refresh, re-count eels.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Sequence, TYPE_CHECKING

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
    post_click_fish_poll_s,
    post_click_fish_wait_s,
    should_seek_fishing_spot,
    wait_for_action_code,
    wait_idle_before_spot_s,
)
from bot_gamestate import inventory_is_full, occupied_cell_count
from bot_inventory_actions import use_named_item_on_named_item
from bot_inventory_items import count_labeled_item_slots, read_inventory_labels
from bot_search import search_with_camera_pan, walk_direction_for_attempt
from .infernal_eel_log import LOGS_DIR, ensure_logs_dir
from .infernal_eel_progress import InventoryProgressScore

if TYPE_CHECKING:
    import bot_arms as Arms
    import bot_client as Client
    import bot_eyes as Eyes

# ``items/<stem>.png`` labels for eel bucket count + hammer→eel use-on (env overrides).
EEL_ITEM_NAME = os.environ.get("EXODIA_INFERNAL_EEL_ITEM", "infernal_eel")
HAMMER_ITEM_NAME = os.environ.get("EXODIA_INFERNAL_HAMMER_ITEM", "hammer")
EEL_INV_TEMPLATE = os.environ.get("EXODIA_INFERNAL_EEL_TEMPLATE", "infernal_eel_fish.png")
HAMMER_INV_TEMPLATE = os.environ.get("EXODIA_INFERNAL_HAMMER_TEMPLATE", "imcando_hammer.png")
SPOT_TEMPLATES: list[str] = [
    t.strip()
    for t in os.environ.get(
        "EXODIA_INFERNAL_SPOT_TEMPLATES", "osrs_infernalEel.png,infernal_eel_spot.png"
    ).split(",")
    if t.strip()
]
INV_SLOT_COUNT = 28
MAX_SPOT_PAN_ATTEMPTS = int(os.environ.get("EXODIA_SPOT_PAN_ATTEMPTS", "8"))
MAX_SPOT_WALK_ATTEMPTS = int(os.environ.get("EXODIA_SPOT_WALK_ATTEMPTS", "4"))
CRACK_TICK_DELAY_S = float(
    os.environ.get("EXODIA_CRACK_TICK_DELAY", str(constants.OSRS_TICK_S))
)
MAX_CRACK_ACTIONS = int(os.environ.get("EXODIA_MAX_CRACK_ACTIONS", "32"))
POST_CLICK_FISH_WAIT_S = float(os.environ.get("EXODIA_POST_CLICK_FISH_WAIT_S", "7"))
POST_CLICK_FISH_POLL_S = float(os.environ.get("EXODIA_POST_CLICK_FISH_POLL_S", "0.75"))
SPOT_TEMPLATE_THRESHOLD = float(os.environ.get("EXODIA_SPOT_THRESHOLD", "0.45"))
INV_TEMPLATE_THRESHOLD = float(os.environ.get("EXODIA_INV_TEMPLATE_THRESHOLD", "0.35"))


def _noop_event(_event: str, **_fields: object) -> None:
    pass


def _noop_last_action(_msg: Optional[str]) -> None:
    pass


_sleep: Callable[[float], None] = time.sleep
_stop_check: Callable[[], bool] = lambda: False
_log_event: Callable[..., None] = _noop_event
_set_last_action: Callable[[Optional[str]], None] = _noop_last_action


class InfernalEelState(Enum):
    FISHING = auto()
    SEEK_SPOT = auto()
    CRACKING = auto()


class CrackPhase(Enum):
    CLICK = auto()
    WAIT_TICK = auto()


@dataclass
class InfernalEelContext:
    client: "Client.ClientWindow"
    bot_e: "Eyes.BotEyes"
    bot_a: "Arms.BotArms"
    state: InfernalEelState = InfernalEelState.SEEK_SPOT
    crack_phase: CrackPhase = CrackPhase.CLICK
    crack_actions: int = 0
    cycles: int = 0
    action_code: int = 2
    eel_count: int = 0
    inv_slots: Optional[int] = None
    inv_full: bool = False
    slot_items: Sequence[Sequence[Optional[str]]] = field(default_factory=list)
    occupancy: Sequence[Sequence[bool]] = field(default_factory=list)
    waiting_for_fish: bool = False
    last_spot_click: Optional[list] = None
    progress: InventoryProgressScore = field(default_factory=InventoryProgressScore)
    need_red_before_spot: bool = False

    def refresh(self, *, record_progress: bool = False) -> None:
        Actions.bot_update(self.client, self.bot_e)
        self.action_code = self.bot_e.get_action_text(refresh=False)
        self.slot_items, self.occupancy = read_inventory_labels(self.bot_e)
        self.eel_count = count_labeled_item_slots(
            self.slot_items, self.occupancy, EEL_ITEM_NAME
        )
        self.inv_slots = occupied_cell_count(self.occupancy)
        self.inv_full = inventory_is_full(self.bot_e)
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
        elif event == "cracking":
            print(
                "Progress +%d (cracking) → score %d | eels %d"
                % (-self.progress.last_delta, self.progress.score, self.eel_count)
            )
        elif event == "inv_change":
            print(
                "Progress +%d (inventory slots) → score %d | inv %s"
                % (abs(self.progress.last_delta), self.progress.score, self.inv_slots)
            )


def should_enter_cracking(ctx: InfernalEelContext) -> bool:
    """Start cracking only when all 28 slots are occupied."""
    return ctx.inv_full


def _save_stagnation_snapshot(ctx: InfernalEelContext) -> None:
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


def _transition(ctx: InfernalEelContext, new: InfernalEelState, reason: str) -> InfernalEelState:
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
    if new == InfernalEelState.CRACKING:
        ctx.crack_phase = CrackPhase.CLICK
        ctx.crack_actions = 0
    return new


def _after_cracking_done(ctx: InfernalEelContext) -> InfernalEelState:
    if is_action_fishing(ctx.action_code):
        return _transition(ctx, InfernalEelState.FISHING, "cracked; green action line")
    if is_action_idle(ctx.action_code):
        return _transition(ctx, InfernalEelState.SEEK_SPOT, "cracked; red action line — seek spot")
    return _transition(ctx, InfernalEelState.SEEK_SPOT, "cracked; no fishing UI — seek spot")


def _locate_spots(bot_e: "Eyes.BotEyes") -> list:
    hits: list = []
    for template in SPOT_TEMPLATES:
        found = bot_e.locate_image(
            filename=template,
            inv=False,
            name="infernal spot %s" % template,
            threshold=SPOT_TEMPLATE_THRESHOLD,
        )
        if found:
            hits.extend(found)
    return hits


class InfernalEelMachine:
    """Question: How do I advance infernal eel fishing one FSM step (fish / seek spot / crack)?

    One ``step()`` = one state action (or cracking sub-step). States: FISHING, SEEK_SPOT, CRACKING.
    """

    def __init__(self, ctx: InfernalEelContext):
        self.ctx = ctx

    def should_throttle(self) -> bool:
        return self.ctx.state in (InfernalEelState.FISHING, InfernalEelState.SEEK_SPOT)

    def step(self) -> None:
        if _stop_check():
            return
        self.ctx.cycles += 1
        self.ctx.refresh(record_progress=True)

        if self.ctx.state == InfernalEelState.FISHING:
            self._step_fishing()
        elif self.ctx.state == InfernalEelState.SEEK_SPOT:
            self._step_seek_spot()
        elif self.ctx.state == InfernalEelState.CRACKING:
            self._step_cracking()

    def _step_fishing(self) -> None:
        ctx = self.ctx
        if should_enter_cracking(ctx):
            inv = ctx.inv_slots
            reason = "inventory full (%d/%d)" % (
                inv if inv is not None else INV_SLOT_COUNT,
                INV_SLOT_COUNT,
            )
            _transition(ctx, InfernalEelState.CRACKING, reason)
            return

        if should_seek_fishing_spot(ctx.action_code):
            ctx.need_red_before_spot = True
            _transition(ctx, InfernalEelState.SEEK_SPOT, "red NOT fishing UI — seek next spot")
            return

        if ctx.action_code == ACTION_NO_UI:
            print("Fishing (green UI hidden) — waiting for red NOT fishing before re-seeking")
            return

        if not is_action_fishing(ctx.action_code):
            print("Unexpected action code %d while fishing — waiting" % ctx.action_code)
            return

        print("Fishing (green action line)")

    def _step_seek_spot(self) -> None:
        ctx = self.ctx
        if should_enter_cracking(ctx):
            _transition(ctx, InfernalEelState.CRACKING, "inventory full — crack before fishing")
            return

        if is_action_fishing(ctx.action_code):
            _transition(ctx, InfernalEelState.FISHING, "green action line — already fishing")
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
            print("Clicked infernal eel spot")
            self._wait_for_fishing_start(ctx)
            return

        print(
            "No infernal eel spot found after %d camera pans and %d walk attempts (tried %s)"
            % (MAX_SPOT_PAN_ATTEMPTS, MAX_SPOT_WALK_ATTEMPTS, ", ".join(SPOT_TEMPLATES))
        )

    def _wait_for_fishing_start(self, ctx: InfernalEelContext) -> bool:
        wait_s = post_click_fish_wait_s(POST_CLICK_FISH_WAIT_S)
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        ctx.waiting_for_fish = True
        _set_last_action("wait_fishing start (%.0fs)" % wait_s)
        _log_event("fsm.wait_fishing", phase="start", wait_s=wait_s, poll_s=poll_s)
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
            _transition(ctx, InfernalEelState.FISHING, "green action line after spot click")
            return True
        if result.cancelled:
            _set_last_action("wait_fishing cancelled")
            return False
        _set_last_action("wait_fishing timeout")
        print(
            "Fishing did not start within %.0fs (%s) — wait for red NOT fishing before next spot"
            % (wait_s, action_code_label(ctx.action_code))
        )
        return False

    def _ready_to_search_spot(self, ctx: InfernalEelContext) -> bool:
        if can_click_fishing_spot(ctx.action_code):
            return True
        if ctx.action_code == ACTION_NO_UI and not ctx.need_red_before_spot:
            return True
        return False

    def _wait_for_not_fishing_ui(self, ctx: InfernalEelContext) -> bool:
        if self._ready_to_search_spot(ctx):
            if ctx.action_code == ACTION_NO_UI and not ctx.need_red_before_spot:
                print("No action strip yet — searching for first spot click")
            return True

        wait_s = wait_idle_before_spot_s()
        poll_s = post_click_fish_poll_s(POST_CLICK_FISH_POLL_S)
        _set_last_action("wait_idle_before_spot (%.0fs)" % wait_s)
        print(
            "Waiting for red NOT fishing UI before spot click (up to %.0fs) — now %s"
            % (wait_s, action_code_label(ctx.action_code))
        )

        def _read_code() -> int:
            ctx.refresh(record_progress=False)
            return ctx.action_code

        result = wait_for_action_code(
            _read_code,
            can_click_fishing_spot,
            timeout_s=wait_s,
            interval_s=poll_s,
            sleep_fn=_sleep,
            stop_check=_stop_check,
        )
        return result.success

    def _click_spot_with_pan(self, ctx: InfernalEelContext) -> bool:
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

        def _on_miss(attempt: int, max_attempts: int) -> None:
            print(
                "No spot — rotating camera (%d/%d)"
                % (attempt, max_attempts)
            )

        walk_wait_s = float(os.environ.get("EXODIA_WALK_WAIT_S", "3.0"))

        def _relocate(walk_i: int, max_walk: int) -> None:
            direction = walk_direction_for_attempt(walk_i - 1)
            _set_last_action("walk_click %s" % direction)
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
        print("Found %d infernal spot hit(s)" % len(hits))
        target = random.choice(hits)
        ctx.last_spot_click = list(target)
        _set_last_action("spot_click %s" % target)
        _log_event("fsm.spot_click", hit_count=len(hits), click_xy=target)
        ctx.need_red_before_spot = True
        ctx.bot_a.click_at(target, rad=11)
        return True

    def _step_cracking(self) -> None:
        ctx = self.ctx
        if ctx.eel_count == 0:
            print("Cracking complete — no infernal eels in inventory")
            _log_event("fsm.cracking", phase="complete", eel_count=0)
            _after_cracking_done(ctx)
            return

        if ctx.crack_phase == CrackPhase.CLICK:
            self._crack_click()
        elif ctx.crack_phase == CrackPhase.WAIT_TICK:
            self._crack_wait_tick()

    def _crack_click(self) -> None:
        ctx = self.ctx
        if ctx.crack_actions >= MAX_CRACK_ACTIONS:
            print("Cracking safety cap (%d actions)" % MAX_CRACK_ACTIONS)
            _after_cracking_done(ctx)
            return

        print(
            "Cracking: %s → %s (%d eel slot(s))"
            % (HAMMER_ITEM_NAME, EEL_ITEM_NAME, ctx.eel_count)
        )
        _log_event(
            "fsm.cracking",
            phase="click",
            eel_count=ctx.eel_count,
            crack_actions=ctx.crack_actions,
        )
        _set_last_action("cracking hammer→eel")

        result = use_named_item_on_named_item(
            ctx.bot_e.inventory_rect,
            ctx.bot_e.client_rect,
            ctx.slot_items,
            HAMMER_ITEM_NAME,
            EEL_ITEM_NAME,
            arms=ctx.bot_a,
        )
        if not result.ok:
            print(
                "Named crack failed (%s) — trying template use_x_on_y"
                % (result.reason or result.missing_item or "unknown")
            )
            result = Actions.use_x_on_y(
                ctx.bot_e,
                ctx.bot_a,
                HAMMER_INV_TEMPLATE,
                EEL_INV_TEMPLATE,
                threshold=INV_TEMPLATE_THRESHOLD,
            )
        if not result.ok:
            print(
                "Cracking failed — %s (%s)"
                % (result.reason, result.missing_item or "unknown")
            )
            _after_cracking_done(ctx)
            return

        ctx.crack_actions += 1
        ctx.crack_phase = CrackPhase.WAIT_TICK

    def _crack_wait_tick(self) -> None:
        ctx = self.ctx
        _set_last_action("cracking tick wait")
        _sleep(CRACK_TICK_DELAY_S)
        ctx.refresh(record_progress=True)
        remaining = ctx.eel_count
        print("  After tick wait: %d eel slot(s) remaining" % remaining)
        _log_event(
            "fsm.cracking",
            phase="wait_tick",
            eel_count=remaining,
            crack_actions=ctx.crack_actions,
        )

        if remaining == 0:
            print("Cracking complete — no infernal eels left")
            _log_event("fsm.cracking", phase="complete", eel_count=0)
            _after_cracking_done(ctx)
            return

        ctx.crack_phase = CrackPhase.CLICK


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
