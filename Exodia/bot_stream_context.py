"""
Stream-first FSM context — window sync, perception refresh, optional event waits.

Primary poll entry: ``tick, events = ctx.refresh()``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple, TYPE_CHECKING

from bot_perception_events import PerceptionEvent
from bot_perception_types import PerceptionTick
from bot_perception_wait import (
    event_kind_predicate,
    inventory_count_increased_predicate,
    wait_for_event as _wait_for_event,
)
from bot_wait import PollResult

if TYPE_CHECKING:
    import bot_arms as Arms
    import bot_client as Client
    from bot_perception_client import PerceptionClient
    from bot_runtime import RuntimeBridge

__all__ = [
    "StreamBotContext",
    "basic_stream_context_from_init",
    "stream_context_from_init",
]


def _sync_window_geometry(client: "Client.ClientWindow") -> None:
    """Refresh Win32 client rect without grabbing a frame."""
    client.update()


@dataclass
class StreamBotContext:
    """Wired session for stream-only FSM bots (no ``BotEyes``)."""

    client: "Client.ClientWindow"
    arms: "Arms.BotArms"
    perception: "PerceptionClient"
    runtime: "RuntimeBridge"

    def refresh(self) -> Tuple[PerceptionTick, List[PerceptionEvent]]:
        """Sync window geometry and return latest tick plus diff events."""
        _sync_window_geometry(self.client)
        return self.perception.refresh_with_events()

    def wait_for_event(
        self,
        predicate: Callable[[PerceptionEvent], bool],
        *,
        timeout_s: float,
        poll_s: float = 0.3,
        sleep_fn: Callable[[float], None] = time.sleep,
        stop_check: Callable[[], bool] = lambda: False,
        on_poll: Optional[Callable[[int, List[PerceptionEvent]], None]] = None,
    ) -> PollResult[PerceptionEvent]:
        """Poll ``refresh()`` until ``predicate`` matches a diff event."""
        return _wait_for_event(
            self.perception,
            predicate,
            timeout_s=timeout_s,
            poll_s=poll_s,
            sync_fn=lambda: _sync_window_geometry(self.client),
            sleep_fn=sleep_fn,
            stop_check=stop_check,
            on_poll=on_poll,
        )

    def wait_for_event_kind(
        self,
        kind: str,
        *,
        timeout_s: float,
        poll_s: float = 0.3,
        sleep_fn: Callable[[float], None] = time.sleep,
        stop_check: Callable[[], bool] = lambda: False,
    ) -> PollResult[PerceptionEvent]:
        """Wait until an event with the given ``kind`` appears."""
        return self.wait_for_event(
            event_kind_predicate(kind),
            timeout_s=timeout_s,
            poll_s=poll_s,
            sleep_fn=sleep_fn,
            stop_check=stop_check,
        )

    def wait_for_item_count_increased(
        self,
        label: str,
        *,
        min_delta: int = 1,
        timeout_s: float,
        poll_s: float = 0.3,
        sleep_fn: Callable[[float], None] = time.sleep,
        stop_check: Callable[[], bool] = lambda: False,
    ) -> PollResult[PerceptionEvent]:
        """Wait until inventory count for ``label`` rises by at least ``min_delta``."""
        return self.wait_for_event(
            inventory_count_increased_predicate(label, min_delta=min_delta),
            timeout_s=timeout_s,
            poll_s=poll_s,
            sleep_fn=sleep_fn,
            stop_check=stop_check,
        )


def stream_context_from_init(
    runtime: "RuntimeBridge",
    *,
    win_rect=None,
    window_title: str = "RuneLite",
    port=None,
    require_calibration: bool = True,
) -> StreamBotContext:
    """Build a :class:`StreamBotContext` via :func:`bot_actions.stream_bot_init`."""
    import bot_actions as Actions

    client, arms, perception = Actions.stream_bot_init(
        win_rect=win_rect,
        window_title=window_title,
        port=port,
        require_calibration=require_calibration,
    )
    return StreamBotContext(
        client=client,
        arms=arms,
        perception=perception,
        runtime=runtime,
    )


def basic_stream_context_from_init(
    runtime: "RuntimeBridge",
    *,
    win_rect=None,
    window_title: str = "RuneLite",
    port=None,
    require_calibration: bool = True,
) -> StreamBotContext:
    """Stream context for basic fishing FSM — configures infernal world watchlist first."""
    from bot_stream_control import configure_infernal_world_watchlist

    configure_infernal_world_watchlist()
    return stream_context_from_init(
        runtime,
        win_rect=win_rect,
        window_title=window_title,
        port=port,
        require_calibration=require_calibration,
    )
