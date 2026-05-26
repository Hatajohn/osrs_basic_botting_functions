"""
Generic timed polling — reusable across bots and FSMs.

``poll_until`` is a simple one-concern wait primitive (predicate loop with timeout;
no perception wiring). Compound waits inject ``read_code`` / domain predicates — e.g.
``bot_action_ui.wait_for_action_code`` — on top of this helper.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")

__all__ = ["PollResult", "poll_until"]


@dataclass(frozen=True)
class PollResult(Generic[T]):
    """Question: What did :func:`poll_until` return?

    Carries ``success``, last ``value``, ``elapsed_s``, ``polls``, and ``cancelled``.
    """

    success: bool
    value: Optional[T]
    elapsed_s: float
    polls: int
    cancelled: bool


def poll_until(
    predicate: Callable[[], Optional[T]],
    *,
    timeout_s: float,
    interval_s: float,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop_check: Callable[[], bool] = lambda: False,
    on_poll: Optional[Callable[[int, Optional[T]], None]] = None,
) -> PollResult[T]:
    """Question: How do I wait until a predicate returns a non-``None`` value?

    ``predicate`` should return the success value when done, or ``None`` to keep
    waiting. The returned :class:`PollResult` carries that value on success.

    Args:
        predicate: Called each poll; non-``None`` return ends the wait successfully.
        timeout_s: Maximum wall time (seconds).
        interval_s: Sleep between polls (seconds).
        sleep_fn: Injectable sleep (tests, interruptible session sleep).
        stop_check: When ``True``, exit early with ``cancelled=True``.
        on_poll: Optional ``(poll_index, last_value)`` hook after each failed poll.
    """
    timeout_s = max(0.0, float(timeout_s))
    interval_s = max(0.0, float(interval_s))
    t0 = time.monotonic()
    polls = 0
    last: Optional[T] = None

    while True:
        if stop_check():
            return PollResult(
                success=False,
                value=last,
                elapsed_s=time.monotonic() - t0,
                polls=polls,
                cancelled=True,
            )

        polls += 1
        last = predicate()
        if last is not None:
            return PollResult(
                success=True,
                value=last,
                elapsed_s=time.monotonic() - t0,
                polls=polls,
                cancelled=False,
            )

        if on_poll is not None:
            on_poll(polls, last)

        if time.monotonic() - t0 >= timeout_s:
            return PollResult(
                success=False,
                value=last,
                elapsed_s=time.monotonic() - t0,
                polls=polls,
                cancelled=False,
            )

        sleep_fn(interval_s)
