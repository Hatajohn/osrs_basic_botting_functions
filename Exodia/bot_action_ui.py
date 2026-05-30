"""
OSRS action-strip tri-state predicates (``BotEyes.get_action_text*`` codes).

Simple — pure int checks and env tunables: ``is_action_*``, ``can_click_fishing_spot``,
``action_code_label``, ``post_click_fish_*_s``, ``wait_idle_before_spot_s``.

Compound — perception poll: ``wait_for_action_code`` (``read_code`` + predicate via
``bot_wait.poll_until``).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from bot_wait import PollResult, poll_until

# Matches ``BotEyes.get_action_text`` return values.
ACTION_FISHING = 0  # green — active skilling action
ACTION_IDLE = 1  # red — action line visible but not actively skilling
ACTION_NO_UI = 2  # strip hidden (often before first cast or after long idle)

__all__ = [
    "ACTION_FISHING",
    "ACTION_IDLE",
    "ACTION_NO_UI",
    "can_seek_fishing_spot",
    "action_code_label",
    "describe_post_click_wait_status",
    "is_action_fishing",
    "is_action_idle",
    "is_fishing_ui_visible",
    "post_click_fish_poll_s",
    "post_click_fish_wait_s",
    "can_click_fishing_spot",
    "should_seek_fishing_spot",
    "wait_for_action_code",
    "wait_idle_before_spot_s",
]


def is_action_fishing(action_code: int) -> bool:
    """Question: Is the action strip showing active skilling (green, code 0)?"""
    return action_code == ACTION_FISHING


def is_action_idle(action_code: int) -> bool:
    """Question: Is the action strip showing idle / ready (red, code 1)?"""
    return action_code == ACTION_IDLE


def is_fishing_ui_visible(action_code: int) -> bool:
    """Question: Is any fishing action strip visible (green or red)?"""
    return action_code in (ACTION_FISHING, ACTION_IDLE)


def should_seek_fishing_spot(action_code: int) -> bool:
    """Question: Should I seek a new fishing spot (red idle strip visible)?"""
    return action_code == ACTION_IDLE


def can_click_fishing_spot(action_code: int) -> bool:
    """Question: Is it safe to click a fishing spot (red idle strip only)?"""
    return is_action_idle(action_code)


def can_seek_fishing_spot(
    action_code: int,
    *,
    need_red_before_spot: bool = False,
) -> bool:
    """Question: May I click or seek a fishing spot (infernal / stream FSM gating)?

    First spot: code ``2`` when ``need_red_before_spot`` is false. Re-click after a
    green session requires confident NOT fishing (code ``1``).
    """
    if can_click_fishing_spot(action_code):
        return True
    if action_code == ACTION_NO_UI and not need_red_before_spot:
        return True
    return False


def action_code_label(action_code: int) -> str:
    """Question: What is the human-readable label for an action code?"""
    return {
        ACTION_FISHING: "FISHING (green UI)",
        ACTION_IDLE: "IDLE (red UI)",
        ACTION_NO_UI: "no fishing UI",
    }.get(action_code, "action code %d" % action_code)


def describe_post_click_wait_status(action_code: int) -> Optional[str]:
    """Question: What should I log while waiting after clicking a fishing spot?

    Returns ``None`` when there is nothing new to log on this poll.
    """
    if is_action_fishing(action_code):
        return None
    if is_action_idle(action_code):
        return "Red fishing UI — at spot but not fishing yet; waiting..."
    if action_code == ACTION_NO_UI:
        return "No fishing UI yet — player may still be moving to spot..."
    return "Unexpected action code %d; waiting..." % action_code


def post_click_fish_wait_s(default: float = 7.0) -> float:
    """Question: How long should I wait after clicking a fishing spot (``EXODIA_POST_CLICK_FISH_WAIT_S``)?"""
    return max(3.0, float(os.environ.get("EXODIA_POST_CLICK_FISH_WAIT_S", str(default))))


def post_click_fish_poll_s(default: float = 0.75) -> float:
    """Question: How often should I poll action UI after a spot click (``EXODIA_POST_CLICK_FISH_POLL_S``)?"""
    return max(0.25, float(os.environ.get("EXODIA_POST_CLICK_FISH_POLL_S", str(default))))


def wait_idle_before_spot_s(default: float = 25.0) -> float:
    """Question: How long should I wait for idle UI before seeking a spot (``EXODIA_WAIT_IDLE_BEFORE_SPOT_S``)?"""
    return max(3.0, float(os.environ.get("EXODIA_WAIT_IDLE_BEFORE_SPOT_S", str(default))))


def wait_for_action_code(
    read_code: Callable[[], int],
    predicate: Callable[[int], bool],
    *,
    timeout_s: float,
    interval_s: float,
    sleep_fn: Callable[[float], None],
    stop_check: Callable[[], bool] = lambda: False,
    on_status: Optional[Callable[[int, int], Optional[str]]] = None,
) -> PollResult[int]:
    """Question: How do I wait until the action strip matches a predicate?

    Polls ``read_code`` until ``predicate(code)`` is true. ``read_code`` should refresh
    perception (e.g. capture + action-strip read) and return the latest code.
    ``on_status``, if set, is ``(poll_index, code) -> message`` for optional logging.
    """

    last_code: list = [ACTION_NO_UI]

    def _pred() -> Optional[int]:
        code = read_code()
        last_code[0] = code
        return code if predicate(code) else None

    def _on_poll(poll_n: int, _last: Optional[int]) -> None:
        if on_status is None:
            return
        msg = on_status(poll_n, last_code[0])
        if msg:
            print("  %s" % msg)

    return poll_until(
        _pred,
        timeout_s=timeout_s,
        interval_s=interval_s,
        sleep_fn=sleep_fn,
        stop_check=stop_check,
        on_poll=_on_poll if on_status else None,
    )
