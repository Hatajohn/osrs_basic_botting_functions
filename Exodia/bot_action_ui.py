"""
OSRS action-strip tri-state (from ``BotEyes.get_action_text*``).

Reusable predicates and wait helpers for any script that keys off the green/red
fishing (or skilling) action line.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from bot_wait import PollResult, poll_until

# Matches ``BotEyes.get_action_text`` / ``get_action_text_robust`` return values.
ACTION_FISHING = 0  # green — active skilling action
ACTION_IDLE = 1  # red — action line visible but not actively skilling
ACTION_NO_UI = 2  # strip hidden (often before first cast or after long idle)

__all__ = [
    "ACTION_FISHING",
    "ACTION_IDLE",
    "ACTION_NO_UI",
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
    return action_code == ACTION_FISHING


def is_action_idle(action_code: int) -> bool:
    return action_code == ACTION_IDLE


def is_fishing_ui_visible(action_code: int) -> bool:
    return action_code in (ACTION_FISHING, ACTION_IDLE)


def should_seek_fishing_spot(action_code: int) -> bool:
    """True when the red NOT fishing strip is visible (spot depleted / ready to re-click)."""
    return action_code == ACTION_IDLE


def can_click_fishing_spot(action_code: int) -> bool:
    """Only click a fishing spot when the red NOT fishing UI is showing."""
    return is_action_idle(action_code)


def action_code_label(action_code: int) -> str:
    return {
        ACTION_FISHING: "FISHING (green UI)",
        ACTION_IDLE: "IDLE (red UI)",
        ACTION_NO_UI: "no fishing UI",
    }.get(action_code, "action code %d" % action_code)


def describe_post_click_wait_status(action_code: int) -> Optional[str]:
    """
    Human-readable status while waiting after clicking a fishing spot.

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
    return max(3.0, float(os.environ.get("EXODIA_POST_CLICK_FISH_WAIT_S", str(default))))


def post_click_fish_poll_s(default: float = 0.75) -> float:
    return max(0.25, float(os.environ.get("EXODIA_POST_CLICK_FISH_POLL_S", str(default))))


def wait_idle_before_spot_s(default: float = 25.0) -> float:
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
    """
    Poll ``read_code`` until ``predicate(code)`` is true.

    ``read_code`` should refresh perception (e.g. capture + OCR) and return the
    latest action-strip code. ``on_status``, if set, is ``(poll_index, code) -> message``
    for optional logging between polls.
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
