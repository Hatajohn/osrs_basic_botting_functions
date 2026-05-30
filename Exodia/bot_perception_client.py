"""
Stream-only perception API for FSM bots — parse ``/meta``, diff events, no ``BotEyes``.

Primary poll entry: ``refresh_with_events()`` → ``(PerceptionTick, list[PerceptionEvent])``.
Startup: ``stream_bot_init()`` in ``bot_actions`` (fail-closed when stream is unavailable).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from bot_capture import capture_stream_enabled, fetch_pristine_client_http, fetch_stream_meta_http, stream_service_port
from bot_perception_events import (
    DEFAULT_STALE_THRESHOLD_MS,
    DEFAULT_WORLD_MOVE_THRESHOLD_PX,
    PerceptionEvent,
    diff_perception,
)
from bot_perception_types import (
    ActionSnapshot,
    InventorySnapshot,
    PerceptionTick,
    WorldHit,
    WorldSnapshot,
    parse_perception_tick,
)

__all__ = [
    "PerceptionClient",
    "StreamUnavailableError",
    "require_stream",
]


class StreamUnavailableError(RuntimeError):
    """Perception stream is down, stale, or not configured (fail-closed)."""


def require_stream() -> None:
    """Raise when stream bots cannot run (stream not explicitly enabled)."""
    if not capture_stream_enabled():
        raise StreamUnavailableError(
            "perception stream required — set EXODIA_STREAM_PORT or EXODIA_CAPTURE_STREAM=1"
        )
    if stream_service_port() <= 0:
        raise StreamUnavailableError("perception stream port not configured (EXODIA_STREAM_PORT)")


class PerceptionClient:
    """HTTP ``/meta`` consumer with typed ticks and client-side event diff."""

    def __init__(
        self,
        port: Optional[int] = None,
        *,
        stale_threshold_ms: Optional[float] = None,
        move_threshold_px: Optional[float] = None,
    ) -> None:
        self._port = port
        self._stale_threshold_ms = (
            float(stale_threshold_ms)
            if stale_threshold_ms is not None
            else DEFAULT_STALE_THRESHOLD_MS
        )
        self._move_threshold_px = (
            float(move_threshold_px)
            if move_threshold_px is not None
            else DEFAULT_WORLD_MOVE_THRESHOLD_PX
        )
        self._last_tick: Optional[PerceptionTick] = None
        self._last_events: List[PerceptionEvent] = []
        self._pristine_bgr: Optional[np.ndarray] = None
        self._pristine_capture_seq: int = -1

    def refresh(self) -> PerceptionTick:
        """Fetch and parse ``/meta``; raise ``StreamUnavailableError`` when down or stale."""
        tick = self._fetch_tick()
        self._last_tick = tick
        return tick

    def refresh_with_events(self) -> Tuple[PerceptionTick, List[PerceptionEvent]]:
        """Primary FSM entry — latest tick plus diff events since the previous refresh."""
        tick = self._fetch_tick()
        prev = self._last_tick
        events = diff_perception(
            prev,
            tick,
            move_threshold_px=self._move_threshold_px,
            stale_threshold_ms=self._stale_threshold_ms,
        )
        self._last_tick = tick
        self._last_events = events
        return tick, events

    def last_events(self) -> List[PerceptionEvent]:
        """Cached events from the most recent ``refresh_with_events()`` call."""
        return list(self._last_events)

    def require_calibrated(self) -> None:
        """Fail fast when inventory geometry is missing from the stream."""
        tick = self._last_tick
        if tick is None:
            tick = self.refresh()
        inv = tick.inventory
        if not inv.calibrated or inv.rect is None:
            raise StreamUnavailableError(
                "inventory_not_calibrated — open inventory in RuneLite or recalibrate"
            )

    def pristine_frame(self) -> np.ndarray:
        """Lazy HTTP pristine client BGR (re-fetches when ``capture_seq`` advances)."""
        tick = self._last_tick
        if tick is None:
            tick = self.refresh()
        if (
            self._pristine_bgr is not None
            and self._pristine_capture_seq == tick.capture_seq
        ):
            return self._pristine_bgr.copy()

        bgr = fetch_pristine_client_http(self._port)
        if bgr is None or bgr.size == 0:
            raise StreamUnavailableError("pristine_frame_unavailable")
        self._pristine_bgr = bgr
        self._pristine_capture_seq = tick.capture_seq
        return bgr.copy()

    def slot_screen_xy(self, row: int, col: int) -> Optional[Tuple[int, int]]:
        """Center of inventory slot ``(row, col)`` in Win32 screen coordinates."""
        tick = self._last_tick
        if tick is None or tick.client_rect is None or tick.inventory.rect is None:
            return None
        from bot_eyes import inventory_slot_screen_xy

        return inventory_slot_screen_xy(tick.inventory.rect, tick.client_rect, row, col)

    def inventory(self) -> InventorySnapshot:
        if self._last_tick is None:
            raise StreamUnavailableError("no_tick — call refresh() first")
        return self._last_tick.inventory

    def world(self) -> WorldSnapshot:
        if self._last_tick is None:
            raise StreamUnavailableError("no_tick — call refresh() first")
        return self._last_tick.world

    def action(self) -> ActionSnapshot:
        if self._last_tick is None:
            raise StreamUnavailableError("no_tick — call refresh() first")
        return self._last_tick.action

    def action_code(self) -> int:
        return self.action().action_code

    def is_fishing(self) -> bool:
        return self.action().is_fishing()

    def count_item(self, name: str) -> int:
        return self.inventory().count_label(name)

    def best_world_hit(self, template: str) -> Optional[WorldHit]:
        """Best ephemeral hit for ``template`` (highest score). Prefers stable tracks when present."""
        world = self.world()
        track = world.best_track(template)
        if track is not None:
            return WorldHit(
                template=track.template,
                client_xy=track.client_xy,
                screen_xy=track.screen_xy,
                score=track.score,
            )
        stem = template.strip()
        if stem.lower().endswith(".png"):
            stem = stem[:-4]
        if not stem:
            return None
        matches = [h for h in world.hits if h.template == stem]
        if not matches:
            return None
        return max(matches, key=lambda h: h.score)

    def _fetch_tick(self) -> PerceptionTick:
        require_stream()
        meta = fetch_stream_meta_http(self._port)
        if meta is None:
            raise StreamUnavailableError("stream_meta_unavailable")
        tick = parse_perception_tick(meta)
        if tick.frame_age_ms >= self._stale_threshold_ms:
            raise StreamUnavailableError(
                "perception_stale: frame_age_ms=%.1f threshold_ms=%.1f"
                % (tick.frame_age_ms, self._stale_threshold_ms)
            )
        return tick
