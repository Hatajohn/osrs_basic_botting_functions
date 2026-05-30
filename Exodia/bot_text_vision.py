"""
Full-client colored text OCR for the live perception stream.

``TextScanWorker`` dequeues from the fanout ``text`` queue, runs ``TextFinder.scan``,
and publishes span data on ``/meta`` ``perception.text``.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from bot_capture import FrameBuffer, FrameSnapshot
from bot_client_text import ClientTextSnapshot, ColoredTextSpan, TextFinder
from bot_frame_dispatch import FrameQueue
from bot_text_query import fishing_relevant_spans
from bot_perception_worker import run_modality_loop


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def text_vision_enabled() -> bool:
    """When false, stream skips ``TextScanWorker`` (``EXODIA_TEXT_VISION``)."""
    return _env_bool("EXODIA_TEXT_VISION", True)


def text_meta_full() -> bool:
    """When false, ``text_meta()`` omits the ``spans`` array (``EXODIA_TEXT_META_FULL``)."""
    return _env_bool("EXODIA_TEXT_META_FULL", True)


def default_text_vision_fps() -> float:
    raw = os.environ.get("EXODIA_TEXT_VISION_FPS", "10").strip()
    try:
        fps = float(raw)
    except ValueError:
        fps = 5.0
    return max(0.5, min(15.0, fps))


@dataclass(frozen=True)
class TextPerceptionSnapshot:
    spans: Tuple[ColoredTextSpan, ...]
    processed_seq: int
    capture_seq: int
    client_size: Tuple[int, int]
    elapsed_ms: float
    vision_fps: float


@dataclass
class TextPerceptionCache:
    """Thread-safe colored text scan state for stream consumers."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _spans: Tuple[ColoredTextSpan, ...] = ()
    _processed_seq: int = 0
    _capture_seq: int = 0
    _client_size: Tuple[int, int] = (0, 0)
    _elapsed_ms: float = 0.0
    _vision_fps: float = 0.0

    def update(
        self,
        snap: ClientTextSnapshot,
        *,
        vision_fps: float = 0.0,
    ) -> None:
        with self._lock:
            self._spans = snap.spans
            self._processed_seq = int(snap.processed_seq)
            self._capture_seq = int(snap.capture_seq)
            self._client_size = (int(snap.client_size[0]), int(snap.client_size[1]))
            self._elapsed_ms = float(snap.elapsed_ms)
            self._vision_fps = float(vision_fps)

    def snapshot(self) -> TextPerceptionSnapshot:
        with self._lock:
            return TextPerceptionSnapshot(
                spans=self._spans,
                processed_seq=self._processed_seq,
                capture_seq=self._capture_seq,
                client_size=self._client_size,
                elapsed_ms=self._elapsed_ms,
                vision_fps=self._vision_fps,
            )

    def text_meta(self) -> Dict[str, Any]:
        snap = self.snapshot()
        meta: Dict[str, Any] = {
            "processed_seq": snap.processed_seq,
            "capture_seq": snap.capture_seq,
            "span_count": len(snap.spans),
            "client_w": snap.client_size[0],
            "client_h": snap.client_size[1],
            "scan_ms": round(snap.elapsed_ms, 1),
            "vision_fps": round(snap.vision_fps, 2),
        }
        if text_meta_full():
            meta["spans"] = [
                {
                    "text": span.text,
                    "color": span.color,
                    "bbox": list(span.bbox),
                    "conf": round(span.conf, 1),
                }
                for span in snap.spans
            ]
        else:
            fishing = fishing_relevant_spans(snap.spans)
            if fishing:
                meta["fishing_spans"] = [
                    {
                        "text": span.text,
                        "color": span.color,
                        "bbox": list(span.bbox),
                        "conf": round(span.conf, 1),
                    }
                    for span in fishing
                ]
        return meta


class TextScanWorker:
    """Daemon thread: full-client colored OCR on fanout text queue frames."""

    def __init__(
        self,
        buffer: FrameBuffer,
        text_cache: TextPerceptionCache,
        *,
        frame_queue: Optional[FrameQueue] = None,
        fps: Optional[float] = None,
    ) -> None:
        self._buffer = buffer
        self._frame_queue = frame_queue
        self._cache = text_cache
        self._fps = fps if fps is not None else default_text_vision_fps()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._actual_fps = 0.0
        self._last_error_log_mono = 0.0

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_vision, name="TextScanWorker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _process_frame(self, snap: FrameSnapshot) -> None:
        client_bgr = snap.bgr
        if client_bgr is None or not getattr(client_bgr, "size", 0):
            return
        result = TextFinder.scan(snap)
        self._cache.update(
            result,
            vision_fps=self._actual_fps if self._actual_fps > 0 else self._fps,
        )

    def _run_vision(self) -> None:
        def _process(snap: FrameSnapshot) -> None:
            try:
                self._process_frame(snap)
            except Exception as exc:
                now = time.monotonic()
                if now - self._last_error_log_mono >= 10.0:
                    self._last_error_log_mono = now
                    print("TextScanWorker error: %s" % exc)

        run_modality_loop(
            frame_queue=self._frame_queue,
            buffer=self._buffer,
            stop_event=self._stop,
            fps=self._fps,
            process_fn=_process,
            idle_wait_s=0.05,
            on_fps=lambda fps: setattr(self, "_actual_fps", fps),
        )


__all__ = [
    "TextPerceptionCache",
    "TextPerceptionSnapshot",
    "TextScanWorker",
    "default_text_vision_fps",
    "text_meta_full",
    "text_vision_enabled",
]
