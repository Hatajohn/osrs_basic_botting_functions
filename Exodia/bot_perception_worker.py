"""
Shared vision-loop helpers for perception modality processors.

When ``EXODIA_FRAME_FANOUT=1``, each modality reads from its own ``FrameQueue``
via ``take_latest()``; otherwise falls back to ``FrameBuffer.latest_copy()``.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from bot_capture import FrameBuffer, FrameSnapshot
from bot_frame_dispatch import FrameQueue


def take_modality_frame(
    frame_queue: Optional[FrameQueue],
    buffer: FrameBuffer,
) -> Optional[FrameSnapshot]:
    """Return the newest frame for a modality consumer."""
    if frame_queue is not None:
        return frame_queue.take_latest()
    return buffer.latest_copy()


def run_modality_loop(
    *,
    frame_queue: Optional[FrameQueue],
    buffer: FrameBuffer,
    stop_event: threading.Event,
    fps: float,
    process_fn: Callable[[FrameSnapshot], None],
    idle_wait_s: float = 0.01,
    on_fps: Optional[Callable[[float], None]] = None,
) -> None:
    """
    Rate-limited vision loop: poll queue/buffer, skip stale seq, call ``process_fn``.

    ``on_fps`` receives measured actual FPS once per second (optional).
    """
    last_processed_seq = 0
    processed = 0
    t0 = time.monotonic()
    actual_fps = 0.0
    min_interval = 1.0 / fps if fps > 0 else 0.0

    while not stop_event.is_set():
        snap = take_modality_frame(frame_queue, buffer)
        if snap is None or snap.seq <= last_processed_seq:
            stop_event.wait(idle_wait_s)
            continue

        if snap.seq > last_processed_seq + 1:
            fresh = take_modality_frame(frame_queue, buffer)
            if fresh is not None:
                snap = fresh

        try:
            process_fn(snap)
        except Exception:
            pass

        last_processed_seq = snap.seq
        processed += 1
        elapsed = time.monotonic() - t0
        if elapsed >= 1.0:
            actual_fps = processed / elapsed
            if on_fps is not None:
                on_fps(actual_fps)
            processed = 0
            t0 = time.monotonic()

        if min_interval > 0:
            stop_event.wait(min_interval)


__all__ = [
    "FrameQueue",
    "run_modality_loop",
    "take_modality_frame",
]
