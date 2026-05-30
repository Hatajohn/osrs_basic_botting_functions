"""
Event-driven perception waits — poll ``/meta`` until a diff event matches.

Built on :func:`bot_wait.poll_until`; FSMs pass predicates over
:class:`~bot_perception_events.PerceptionEvent` instances.
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional, Tuple

from bot_perception_client import PerceptionClient
from bot_perception_events import InventoryCountChanged, PerceptionEvent
from bot_perception_types import PerceptionTick
from bot_wait import PollResult, poll_until

__all__ = [
    "event_kind_predicate",
    "inventory_count_increased_predicate",
    "wait_for_event",
]


def event_kind_predicate(kind: str) -> Callable[[PerceptionEvent], bool]:
    """Match events by ``kind`` discriminator string."""

    def _pred(event: PerceptionEvent) -> bool:
        return event.kind == kind

    return _pred


def inventory_count_increased_predicate(
    label: str,
    *,
    min_delta: int = 1,
) -> Callable[[PerceptionEvent], bool]:
    """Match ``InventoryCountChanged`` when ``label`` count rose by at least ``min_delta``."""

    stem = (label or "").strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]

    def _pred(event: PerceptionEvent) -> bool:
        if not isinstance(event, InventoryCountChanged):
            return False
        if event.label != stem:
            return False
        return event.delta >= min_delta

    return _pred


def wait_for_event(
    perception: PerceptionClient,
    predicate: Callable[[PerceptionEvent], bool],
    *,
    timeout_s: float,
    poll_s: float = 0.3,
    sync_fn: Optional[Callable[[], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop_check: Callable[[], bool] = lambda: False,
    on_poll: Optional[Callable[[int, List[PerceptionEvent]], None]] = None,
) -> PollResult[PerceptionEvent]:
    """Poll perception until ``predicate`` matches one emitted diff event.

    Each poll calls ``sync_fn`` (if set), then ``perception.refresh_with_events()``.
    Returns the first matching event on success.
    """
    last_events: List[PerceptionEvent] = []

    def _pred() -> Optional[PerceptionEvent]:
        if sync_fn is not None:
            sync_fn()
        _tick, events = perception.refresh_with_events()
        last_events.clear()
        last_events.extend(events)
        for event in events:
            if predicate(event):
                return event
        return None

    def _on_poll(poll_n: int, _last: Optional[PerceptionEvent]) -> None:
        if on_poll is not None:
            on_poll(poll_n, list(last_events))

    return poll_until(
        _pred,
        timeout_s=timeout_s,
        interval_s=poll_s,
        sleep_fn=sleep_fn,
        stop_check=stop_check,
        on_poll=_on_poll if on_poll else None,
    )
