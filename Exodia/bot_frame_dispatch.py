"""
Per-consumer frame fanout for the capture pipeline.

``CaptureProducer`` publishes once to ``FrameBuffer``, then ``FrameFanout``
offers a copy of each new frame to every registered ``FrameQueue``. Queues are
bounded (``EXODIA_FRAME_QUEUE_DEPTH``, default 1) with keep-latest drop-old
semantics on ``offer``.
"""
from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from bot_capture import FrameSnapshot

__all__ = [
    "FrameQueue",
    "FrameFanout",
    "frame_fanout_enabled",
    "default_frame_queue_depth",
]


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def default_frame_queue_depth() -> int:
    return max(1, _env_int("EXODIA_FRAME_QUEUE_DEPTH", 1))


def frame_fanout_enabled() -> bool:
    """When false, ``CaptureProducer`` skips fanout dispatch (``EXODIA_FRAME_FANOUT``)."""
    return _env_bool("EXODIA_FRAME_FANOUT", False)


def _snapshot_copy(snap: FrameSnapshot) -> FrameSnapshot:
    return FrameSnapshot(
        bgr=snap.bgr.copy(),
        seq=snap.seq,
        ts=snap.ts,
        client_rect=list(snap.client_rect),
        age_ms=snap.age_ms,
    )


@dataclass
class FrameQueue:
    """Thread-safe bounded frame queue (keep-latest drop-old on ``offer``)."""

    _depth: int = field(default_factory=default_frame_queue_depth)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _items: Deque[FrameSnapshot] = field(default_factory=deque)

    @property
    def depth(self) -> int:
        return self._depth

    def offer(self, snap: FrameSnapshot) -> None:
        """Enqueue a frame copy; drop oldest entries when at capacity."""
        copy = _snapshot_copy(snap)
        with self._lock:
            self._items.append(copy)
            while len(self._items) > self._depth:
                self._items.popleft()

    def poll(self) -> Optional[FrameSnapshot]:
        """Remove and return the oldest queued frame, or ``None``."""
        with self._lock:
            if not self._items:
                return None
            return self._items.popleft()

    def peek_latest(self) -> Optional[FrameSnapshot]:
        """Copy of the newest frame without removing it."""
        with self._lock:
            if not self._items:
                return None
            return _snapshot_copy(self._items[-1])

    def take_latest(self) -> Optional[FrameSnapshot]:
        """Drain the queue and return the newest frame (keep-latest consumer)."""
        with self._lock:
            if not self._items:
                return None
            snap = self._items[-1]
            self._items.clear()
            return _snapshot_copy(snap)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass
class FrameFanout:
    """Named per-consumer queues fed from a single capture publish."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _queues: Dict[str, FrameQueue] = field(default_factory=dict)

    def register(self, name: str) -> FrameQueue:
        """Return (or create) the ``FrameQueue`` for ``name``."""
        key = str(name).strip()
        if not key:
            raise ValueError("FrameFanout.register requires a non-empty name")
        with self._lock:
            queue = self._queues.get(key)
            if queue is None:
                queue = FrameQueue()
                self._queues[key] = queue
            return queue

    def unregister(self, name: str) -> None:
        key = str(name).strip()
        with self._lock:
            queue = self._queues.pop(key, None)
        if queue is not None:
            with queue._lock:
                queue._items.clear()

    def dispatch(self, snap: FrameSnapshot) -> None:
        """Offer a frame copy to every registered queue."""
        with self._lock:
            if not self._queues:
                return
            queues = list(self._queues.values())
        for queue in queues:
            queue.offer(snap)

    def queue_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._queues.keys())
