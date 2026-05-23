"""
Decoupled streaming capture for Exodia.

**CaptureProducer** — timer-driven screen grabs only (no vision).
**VisionProcessor** — separate thread; ``bot_track`` on new frames → ``PerceptionCache``.
**FrameBuffer** — depth-1 drop-old latest frame for harness / MJPEG consumers.
"""
from __future__ import annotations

import base64
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

import cv2
import numpy as np

import constants

if TYPE_CHECKING:
    from bot_track import TrackState

Rect = List[int]

__all__ = [
    "FrameBuffer",
    "FrameSnapshot",
    "PerceptionCache",
    "PerceptionSnapshot",
    "WslPsCaptureSession",
    "CaptureProducer",
    "VisionProcessor",
    "CapturePipeline",
    "CaptureStream",
    "start_capture_pipeline",
    "stop_capture_pipeline",
    "capture_stream_latest",
    "get_capture_pipeline",
    "capture_stream_enabled",
    "default_capture_fps",
]

_MIN_CAPTURE_FPS = 2.0 / constants.OSRS_TICK_S


@dataclass(frozen=True)
class FrameSnapshot:
    bgr: np.ndarray
    seq: int
    ts: float
    client_rect: Rect


@dataclass
class FrameBuffer:
    """Thread-safe depth-1 frame store (drop-old on publish)."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _seq: int = 0
    _ts: float = 0.0
    _bgr: Optional[np.ndarray] = None
    _client_rect: Rect = field(default_factory=list)

    def publish(self, bgr: np.ndarray, client_rect: Rect) -> int:
        with self._lock:
            self._seq += 1
            self._ts = time.monotonic()
            self._bgr = np.asarray(bgr, dtype=np.uint8).copy()
            self._client_rect = [int(x) for x in client_rect]
            return self._seq

    def latest_copy(self) -> Optional[FrameSnapshot]:
        with self._lock:
            if self._bgr is None:
                return None
            return FrameSnapshot(
                bgr=self._bgr.copy(),
                seq=self._seq,
                ts=self._ts,
                client_rect=list(self._client_rect),
            )

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    @property
    def age_ms(self) -> float:
        with self._lock:
            if self._bgr is None:
                return float("inf")
            return (time.monotonic() - self._ts) * 1000.0


@dataclass(frozen=True)
class PerceptionSnapshot:
    tracks: Tuple[Dict[str, Any], ...]
    motion_magnitude: float
    processed_seq: int
    capture_seq: int
    ts: float
    track_count: int


@dataclass
class PerceptionCache:
    """Latest vision output for harness / MJPEG (written by VisionProcessor)."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _tracks: Tuple[Dict[str, Any], ...] = ()
    _motion_magnitude: float = 0.0
    _processed_seq: int = 0
    _capture_seq: int = 0
    _ts: float = 0.0
    _vision_fps: float = 0.0

    def update(
        self,
        tracks: List[Dict[str, Any]],
        *,
        motion_magnitude: float,
        processed_seq: int,
        capture_seq: int,
        vision_fps: float = 0.0,
    ) -> None:
        with self._lock:
            self._tracks = tuple(tracks)
            self._motion_magnitude = float(motion_magnitude)
            self._processed_seq = int(processed_seq)
            self._capture_seq = int(capture_seq)
            self._ts = time.monotonic()
            self._vision_fps = float(vision_fps)

    def snapshot(self) -> PerceptionSnapshot:
        with self._lock:
            return PerceptionSnapshot(
                tracks=self._tracks,
                motion_magnitude=self._motion_magnitude,
                processed_seq=self._processed_seq,
                capture_seq=self._capture_seq,
                ts=self._ts,
                track_count=len(self._tracks),
            )


def default_capture_fps() -> float:
    raw = os.environ.get("EXODIA_CAPTURE_FPS", "4").strip()
    try:
        fps = float(raw)
    except ValueError:
        fps = 4.0
    return max(_MIN_CAPTURE_FPS, fps)


def capture_stream_enabled(stream_port_hint: Optional[int] = None) -> bool:
    raw = os.environ.get("EXODIA_CAPTURE_STREAM", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    if stream_port_hint is not None:
        return int(stream_port_hint) > 0
    port = os.environ.get("EXODIA_STREAM_PORT", "").strip()
    if not port:
        return False
    try:
        return int(port) > 0
    except ValueError:
        return False


def _capture_stale_ms() -> float:
    raw = os.environ.get("EXODIA_CAPTURE_STALE_MS", "600").strip()
    try:
        return float(raw)
    except ValueError:
        return 600.0


def _powershell_exe() -> str:
    import shutil

    o = shutil.which(os.environ.get("EXODIA_POWERSHELL_EXE") or "")
    cand = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    return str(Path(o).expanduser() if o else cand)


_WSL_PS_LOOP = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "Add-Type -AssemblyName System.Drawing; "
    "$in=[Console]::In; "
    "while ($true) { "
    "  $line=$in.ReadLine(); "
    "  if ($null -eq $line -or $line -eq 'QUIT') { break }; "
    "  $p=$line -split '\\s+'; "
    "  if ($p.Count -lt 4) { continue }; "
    "  $l=[int]$p[0]; $t=[int]$p[1]; $w=[int]$p[2]; $h=[int]$p[3]; "
    "  $bmp=New-Object System.Drawing.Bitmap $w,$h; "
    "  $g=[System.Drawing.Graphics]::FromImage($bmp); "
    "  $g.CopyFromScreen($l,$t,0,0,$bmp.Size); $g.Dispose(); "
    "  $ms=New-Object System.IO.MemoryStream; "
    "  $bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png); "
    "  $bmp.Dispose(); "
    "  [Convert]::ToBase64String($ms.ToArray()); "
    "  $ms.Dispose() "
    "}"
)


class WslPsCaptureSession:
    """Persistent PowerShell GDI capture (stdin L T W H → stdout base64 PNG)."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def _start(self) -> None:
        exe = _powershell_exe()
        if not Path(exe).is_file():
            raise RuntimeError("wsl_ps session: PowerShell not found at %s" % exe)
        self._proc = subprocess.Popen(
            [exe, "-NoProfile", "-Command", _WSL_PS_LOOP],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _restart(self) -> None:
        self.close()
        self._start()

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write("QUIT\n")
                proc.stdin.flush()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    def grab(self, left: int, top: int, w: int, h: int) -> np.ndarray:
        last_err: Optional[Exception] = None
        for _attempt in range(3):
            with self._lock:
                try:
                    if self._proc is None or self._proc.poll() is not None:
                        self._restart()
                    assert self._proc is not None and self._proc.stdin and self._proc.stdout
                    cmd = "%d %d %d %d\n" % (int(left), int(top), int(w), int(h))
                    self._proc.stdin.write(cmd)
                    self._proc.stdin.flush()
                    line = self._proc.stdout.readline()
                    if not line or not line.strip():
                        raise RuntimeError("wsl_ps session: empty response")
                    raw = base64.b64decode(line.strip())
                    arr = np.frombuffer(raw, dtype=np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is None or img.size == 0:
                        raise RuntimeError("wsl_ps session: decode failed")
                    return img
                except Exception as exc:
                    last_err = exc
                    self._restart()
        raise RuntimeError("wsl_ps session grab failed after retries: %s" % last_err)


_wsl_session: Optional[WslPsCaptureSession] = None
_wsl_session_lock = threading.Lock()


def get_wsl_ps_session() -> WslPsCaptureSession:
    global _wsl_session
    with _wsl_session_lock:
        if _wsl_session is None:
            _wsl_session = WslPsCaptureSession()
        return _wsl_session


class CaptureProducer:
    """Timer-driven grab loop — no vision imports."""

    def __init__(
        self,
        buffer: FrameBuffer,
        client_rect: Rect,
        fps: float,
        grab_fn: Callable[[Rect], np.ndarray],
    ) -> None:
        self._buffer = buffer
        self._client_rect = [int(x) for x in client_rect]
        self._fps = max(_MIN_CAPTURE_FPS, float(fps))
        self._grab_fn = grab_fn
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._actual_fps: float = 0.0

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    def set_client_rect(self, rect: Rect) -> None:
        self._client_rect = [int(x) for x in rect]

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="CaptureProducer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        interval = 1.0 / self._fps
        grabs = 0
        t0 = time.monotonic()
        while not self._stop.is_set():
            loop_start = time.monotonic()
            try:
                bgr = self._grab_fn(self._client_rect)
                if bgr is not None and bgr.size > 0:
                    self._buffer.publish(bgr, self._client_rect)
                    grabs += 1
            except Exception:
                pass
            elapsed = time.monotonic() - t0
            if elapsed >= 1.0:
                self._actual_fps = grabs / elapsed
                grabs = 0
                t0 = time.monotonic()
            sleep_for = interval - (time.monotonic() - loop_start)
            if sleep_for > 0:
                self._stop.wait(sleep_for)


class VisionProcessor:
    """Consumes new ``FrameBuffer`` seq → ``bot_track`` → ``PerceptionCache``."""

    def __init__(
        self,
        buffer: FrameBuffer,
        cache: PerceptionCache,
        *,
        fps: float = 0.0,
        static_exclude: Optional[List[Rect]] = None,
        pan_in_progress: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._buffer = buffer
        self._cache = cache
        self._fps = float(fps) if fps > 0 else 0.0
        self._static_exclude = static_exclude or []
        self._pan_in_progress = pan_in_progress or (lambda: False)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_processed_seq = 0
        self._track_state: Optional[TrackState] = None
        self._actual_fps: float = 0.0

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    def set_static_exclude(self, rects: List[Rect]) -> None:
        self._static_exclude = [list(r) for r in rects]

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="VisionProcessor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        from bot_track import TrackState, default_track_config, track_blobs_from_frame, tracks_to_dict

        processed = 0
        t0 = time.monotonic()
        min_interval = (1.0 / self._fps) if self._fps > 0 else 0.0

        if self._track_state is None:
            self._track_state = TrackState()

        while not self._stop.is_set():
            snap = self._buffer.latest_copy()
            if snap is None or snap.seq <= self._last_processed_seq:
                self._stop.wait(0.02)
                continue

            if snap.seq > self._last_processed_seq + 1:
                fresh = self._buffer.latest_copy()
                if fresh is not None:
                    snap = fresh

            state = self._track_state
            assert state is not None
            state.pan_in_progress = bool(self._pan_in_progress())
            h0, w0 = snap.bgr.shape[:2]
            cfg = default_track_config(w0, h0, capture_fps=default_capture_fps())

            tracks, motion_mag = track_blobs_from_frame(
                snap.bgr,
                state,
                static_exclude=self._static_exclude,
                config=cfg,
            )
            self._last_processed_seq = snap.seq
            self._cache.update(
                tracks_to_dict(tracks),
                motion_magnitude=motion_mag,
                processed_seq=snap.seq,
                capture_seq=self._buffer.seq,
                vision_fps=self._actual_fps,
            )
            processed += 1
            elapsed = time.monotonic() - t0
            if elapsed >= 1.0:
                self._actual_fps = processed / elapsed
                processed = 0
                t0 = time.monotonic()

            if min_interval > 0:
                self._stop.wait(min_interval)


class CapturePipeline:
    """Owns buffer, cache, producer, and vision threads."""

    def __init__(
        self,
        client_rect: Rect,
        *,
        fps: Optional[float] = None,
        vision_fps: float = 0.0,
    ) -> None:
        self.buffer = FrameBuffer()
        self.cache = PerceptionCache()
        self._client_rect = [int(x) for x in client_rect]
        self._fps = fps if fps is not None else default_capture_fps()
        self._vision_fps = vision_fps
        self._static_exclude: List[Rect] = []
        self._pan_flag = False
        self._producer: Optional[CaptureProducer] = None
        self._vision: Optional[VisionProcessor] = None

    def set_geometry(
        self,
        client_rect: Rect,
        inventory_rect: Optional[Rect] = None,
        chat_rect: Optional[Rect] = None,
    ) -> None:
        self._client_rect = [int(x) for x in client_rect]
        exclude: List[Rect] = []
        if inventory_rect and len(inventory_rect) == 4:
            exclude.append(list(inventory_rect))
        if chat_rect and len(chat_rect) == 4:
            exclude.append(list(chat_rect))
        self._static_exclude = exclude
        if self._producer is not None:
            self._producer.set_client_rect(self._client_rect)
        if self._vision is not None:
            self._vision.set_static_exclude(exclude)

    def set_pan_in_progress(self, active: bool) -> None:
        self._pan_flag = bool(active)

    def _pan_cb(self) -> bool:
        return self._pan_flag

    def _make_grab_fn(self) -> Callable[[Rect], np.ndarray]:
        import bot_env as Env

        backend = Env.capture_backend_label()
        if backend == "wsl_ps":
            session = get_wsl_ps_session()

            def grab(rect: Rect) -> np.ndarray:
                l, t, w, h = [int(v) for v in rect]
                return session.grab(l, t, w, h)

            return grab

        def grab(rect: Rect) -> np.ndarray:
            return Env._grab_bgr_sync(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))

        return grab

    def start(self) -> None:
        if self._producer is not None:
            return
        grab_fn = self._make_grab_fn()
        self._producer = CaptureProducer(self.buffer, self._client_rect, self._fps, grab_fn)
        vfps = self._vision_fps
        if vfps <= 0:
            raw = os.environ.get("EXODIA_VISION_FPS", "0").strip()
            try:
                vfps = float(raw)
            except ValueError:
                vfps = 0.0
        self._vision = VisionProcessor(
            self.buffer,
            self.cache,
            fps=vfps,
            static_exclude=self._static_exclude,
            pan_in_progress=self._pan_cb,
        )
        self._producer.start()
        self._vision.start()

    def stop(self) -> None:
        if self._vision is not None:
            self._vision.stop()
            self._vision = None
        if self._producer is not None:
            self._producer.stop()
            self._producer = None

    @property
    def capture_fps(self) -> float:
        if self._producer is None:
            return 0.0
        return self._producer.actual_fps

    @property
    def vision_fps(self) -> float:
        if self._vision is None:
            return 0.0
        return self._vision.actual_fps


CaptureStream = CapturePipeline

_pipeline: Optional[CapturePipeline] = None
_pipeline_lock = threading.Lock()


def get_capture_pipeline() -> Optional[CapturePipeline]:
    return _pipeline


def _stop_pipeline_locked() -> None:
    """Stop active pipeline; caller must hold ``_pipeline_lock``."""
    global _pipeline
    if _pipeline is not None:
        _pipeline.stop()
        _pipeline = None


def _close_wsl_session() -> None:
    global _wsl_session
    with _wsl_session_lock:
        if _wsl_session is not None:
            _wsl_session.close()
            _wsl_session = None


def start_capture_pipeline(
    client_rect: Rect,
    *,
    fps: Optional[float] = None,
    vision_fps: float = 0.0,
) -> CapturePipeline:
    global _pipeline
    with _pipeline_lock:
        _stop_pipeline_locked()
        pipe = CapturePipeline(client_rect, fps=fps, vision_fps=vision_fps)
        pipe.start()
        _pipeline = pipe
        return pipe


def stop_capture_pipeline() -> None:
    with _pipeline_lock:
        _stop_pipeline_locked()
    _close_wsl_session()


def capture_stream_latest(rect: Optional[Rect] = None) -> Optional[np.ndarray]:
    """Copy of latest buffered BGR frame, or ``None`` if pipeline off/stale."""
    pipe = _pipeline
    if pipe is None or not capture_stream_enabled():
        return None
    if pipe.buffer.age_ms > _capture_stale_ms():
        return None
    snap = pipe.buffer.latest_copy()
    if snap is None:
        return None
    return snap.bgr.copy()
