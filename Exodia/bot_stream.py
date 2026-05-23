"""
MJPEG frame publisher for live agent vision over HTTP.

Encodes crops as JPEG and serves multipart MJPEG streams plus single-frame
snapshots. ``CaptureStreamPublisher`` reads the decoupled capture buffer +
``PerceptionCache`` on its own timer (no vision work in the HTTP thread).
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import bot_eyes as Eyes
    from bot_capture import CapturePipeline, PerceptionCache

__all__ = [
    "FramePublisher",
    "CaptureStreamPublisher",
    "MJPEGStreamServer",
]

BOUNDARY = b"frame"


class FramePublisher:
    """Holds latest JPEG bytes per logical stream key."""

    STREAM_KEYS = (
        "world_masked",
        "inventory",
        "action_strip",
        "chat_strip",
        "playspace",
        "playspace_blobs",
    )

    def __init__(self) -> None:
        self._frames: Dict[str, bytes] = {}
        self._meta: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def publish(self, name: str, jpeg_bytes: bytes) -> None:
        with self._lock:
            self._frames[name] = jpeg_bytes

    def get(self, name: str) -> Optional[bytes]:
        with self._lock:
            return self._frames.get(name)

    def set_meta(self, meta: Dict[str, Any]) -> None:
        with self._lock:
            self._meta = dict(meta)

    def get_meta(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._meta)

    def available_streams(self) -> Dict[str, bool]:
        with self._lock:
            return {k: k in self._frames for k in self.STREAM_KEYS}

    def publish_from_eyes(self, eyes: "Eyes.BotEyes") -> None:
        """Encode crops already in memory from the last ``BotEyes.capture_frame()``."""
        import cv2  # noqa: PLC0415
        import bot_eyes as Eyes  # noqa: PLC0415

        def _encode(img) -> Optional[bytes]:
            if img is None or not getattr(img, "size", 0):
                return None
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            return buf.tobytes() if ok else None

        if eyes.curr_client is not None:
            data = _encode(eyes.curr_client)
            if data:
                self.publish("world_masked", data)

        inv = getattr(eyes, "curr_inventory", None)
        if inv is not None:
            data = _encode(inv)
            if data:
                self.publish("inventory", data)

        action = eyes.crop_client_local(list(Eyes.ACTION_STRIP_ROI_CLIENT_LOCAL))
        if action is not None:
            data = _encode(action)
            if data:
                self.publish("action_strip", data)

        if eyes.chat_rect and len(eyes.chat_rect) == 4:
            chat = eyes.crop_client_local(list(eyes.chat_rect))
            if chat is not None:
                data = _encode(chat)
                if data:
                    self.publish("chat_strip", data)


class CaptureStreamPublisher:
    """
    Timer consumer: ``FrameBuffer`` + ``PerceptionCache`` → JPEG streams.

    Does not run blob detection — only encodes frames and overlay from cache.
    """

    def __init__(
        self,
        publisher: FramePublisher,
        pipeline: "CapturePipeline",
        *,
        fps: float = 0.0,
    ) -> None:
        self._publisher = publisher
        self._pipeline = pipeline
        raw = fps if fps > 0 else os.environ.get("EXODIA_STREAM_PUBLISH_FPS", "4")
        try:
            self._fps = max(2.0, float(raw))
        except (TypeError, ValueError):
            self._fps = 4.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="CaptureStreamPublisher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        import cv2  # noqa: PLC0415
        from bot_search import playspace_search_roi
        from bot_track import overlay_tracks, playspace_bgr_from_frame, Track

        interval = 1.0 / self._fps
        while not self._stop.is_set():
            t0 = time.monotonic()
            snap = self._pipeline.buffer.latest_copy()
            pcache = self._pipeline.cache.snapshot()
            if snap is not None:
                play = playspace_bgr_from_frame(snap.bgr)
                if play is not None:
                    ok, buf = cv2.imencode(".jpg", play, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if ok:
                        self._publisher.publish("playspace", buf.tobytes())

                    tracks = [
                        Track(
                            track_id=int(t["id"]),
                            centroid=(int(t["centroid"][0]), int(t["centroid"][1])),
                            bbox=list(t["bbox"]),
                            area=float(t.get("area", 0)),
                        )
                        for t in pcache.tracks
                    ]
                    overlay = overlay_tracks(snap.bgr, tracks)
                    ok2, buf2 = cv2.imencode(".jpg", overlay, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if ok2:
                        self._publisher.publish("playspace_blobs", buf2.tobytes())

                self._publisher.set_meta(
                    {
                        "capture_seq": snap.seq,
                        "processed_seq": pcache.processed_seq,
                        "seq_lag": snap.seq - pcache.processed_seq,
                        "client_rect": list(snap.client_rect),
                        "track_count": pcache.track_count,
                        "motion_magnitude": pcache.motion_magnitude,
                        "capture_fps": self._pipeline.capture_fps,
                        "vision_fps": self._pipeline.vision_fps,
                        "ts": snap.ts,
                    }
                )

            sleep_for = interval - (time.monotonic() - t0)
            if sleep_for > 0:
                self._stop.wait(sleep_for)


def _make_handler(publisher: FramePublisher):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                streams = publisher.available_streams()
                body = "Exodia MJPEG streams\n\n"
                for name, ready in sorted(streams.items()):
                    status = "ready" if ready else "waiting"
                    body += "/stream/%s (%s)\n/snapshot/%s\n\n" % (name, status, name)
                body += "/meta\n/snapshot/meta.json\n"
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path in ("/meta", "/snapshot/meta.json"):
                meta = publisher.get_meta()
                data = json.dumps(meta, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path.startswith("/stream/"):
                name = path.split("/", 2)[2]
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "multipart/x-mixed-replace; boundary=%s" % BOUNDARY.decode("ascii"),
                )
                self.end_headers()
                try:
                    while True:
                        jpeg = publisher.get(name)
                        if jpeg:
                            self.wfile.write(b"--%s\r\n" % BOUNDARY)
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(jpeg))
                            self.wfile.write(jpeg)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    return

            if path.startswith("/snapshot/"):
                name = path.split("/", 2)[2]
                if name == "meta.json":
                    meta = publisher.get_meta()
                    data = json.dumps(meta, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                jpeg = publisher.get(name)
                if not jpeg:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
                return

            self.send_response(404)
            self.end_headers()

    return Handler


class MJPEGStreamServer:
    """Daemon HTTP server exposing ``FramePublisher`` streams."""

    def __init__(
        self,
        port: int = 8765,
        host: str = "127.0.0.1",
        publisher: Optional[FramePublisher] = None,
        stream_publisher: Optional[CaptureStreamPublisher] = None,
    ) -> None:
        self.port = port
        self.host = host
        self.publisher = publisher if publisher is not None else FramePublisher()
        self.stream_publisher = stream_publisher
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def from_env(cls) -> Optional["MJPEGStreamServer"]:
        raw = os.environ.get("EXODIA_STREAM_PORT", "8765").strip()
        port = int(raw or "0")
        if port <= 0:
            return None
        return cls(port=port)

    def start_daemon(self) -> None:
        if self._thread is not None:
            return
        if self.stream_publisher is not None:
            self.stream_publisher.start()
        handler = _make_handler(self.publisher)
        self._httpd = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.stream_publisher is not None:
            self.stream_publisher.stop()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
        self._thread = None

    @property
    def base_url(self) -> str:
        return "http://%s:%d" % (self.host, self.port)
