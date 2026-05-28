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
    from bot_inventory_vision import InventoryPerceptionCache

__all__ = [
    "FramePublisher",
    "CaptureStreamPublisher",
    "PerceptionStreamPublisher",
    "MJPEGStreamServer",
    "publish_game_preview",
    "preview_dimensions",
    "preview_max_width",
    "GAME_PREVIEW_MAX_WIDTH",
]

BOUNDARY = b"frame"
GAME_PREVIEW_MAX_WIDTH = 640


def preview_max_width() -> int:
    """Default preview scale — matches ``EXODIA_DEBUG_FRAME_MAX_WIDTH`` / UI stream max width."""
    raw = os.environ.get("EXODIA_DEBUG_FRAME_MAX_WIDTH", str(GAME_PREVIEW_MAX_WIDTH))
    try:
        width = int(raw)
    except (TypeError, ValueError):
        width = GAME_PREVIEW_MAX_WIDTH
    return width if width > 0 else GAME_PREVIEW_MAX_WIDTH


def preview_dimensions(frame_w: int, frame_h: int, max_width: int) -> tuple[int, int]:
    """Display size after max-width downscale (same contract as ``bot_chain._frame_display_scale``)."""
    w, h = int(frame_w), int(frame_h)
    mw = int(max_width)
    if w <= mw or mw <= 0:
        return w, h
    scale = mw / float(w)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def _baked_overlay_enabled() -> bool:
    """Server-side inventory/world JPEG composite (off by default; UI draws debug overlays client-side)."""
    return os.environ.get("EXODIA_STREAM_BAKED_OVERLAY", "0").strip().lower() in ("1", "true", "yes")


def _encode_jpeg(img, quality: int = 85) -> Optional[bytes]:
    import cv2  # noqa: PLC0415

    if img is None or not getattr(img, "size", 0):
        return None
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else None


def _resize_for_preview(img, max_width: int = GAME_PREVIEW_MAX_WIDTH):
    import cv2  # noqa: PLC0415

    if img is None or not getattr(img, "size", 0):
        return None
    h, w = img.shape[:2]
    new_w, new_h = preview_dimensions(w, h, max_width)
    if new_w == w and new_h == h:
        return img
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def publish_game_preview(
    publisher: "FramePublisher",
    bgr,
    *,
    max_width: Optional[int] = None,
    quality: int = 80,
) -> None:
    """Downscaled pristine client JPEG for UI preview (no inventory overlay)."""
    mw = int(max_width) if max_width is not None else preview_max_width()
    preview = _resize_for_preview(bgr, max_width=mw)
    data = _encode_jpeg(preview, quality=quality)
    if data:
        publisher.publish("game_preview", data)


def publish_pristine_client_snapshot(
    publisher: "FramePublisher",
    bgr,
    *,
    quality: int = 92,
) -> None:
    """Full-resolution pristine client JPEG for template matching / actions."""
    data = _encode_jpeg(bgr, quality=quality)
    if data:
        publisher.publish("pristine_client", data)


def publish_inventory_overlay_live(
    publisher: "FramePublisher",
    bgr,
    inv_cache: "InventoryPerceptionCache",
    *,
    world_cache: Any = None,
    max_width: Optional[int] = None,
    quality: int = 80,
) -> None:
    """Composite inventory + world detect on a **copy** of the live frame (display only)."""
    import numpy as np
    from bot_inventory_items import draw_inventory_item_identify_overlay

    mw = int(max_width) if max_width is not None else preview_max_width()
    snap = inv_cache.snapshot()
    inv_rect = snap.inventory_rect
    if bgr is None or not getattr(bgr, "size", 0):
        return

    pristine = np.asarray(bgr, dtype=np.uint8).copy()

    if inv_rect is not None and len(inv_rect) == 4:
        occ = [list(row) for row in snap.occupancy]
        items = [list(row) for row in snap.slot_items]
        overlay_bgr = draw_inventory_item_identify_overlay(pristine, inv_rect, items, occ)
    else:
        overlay_bgr = pristine

    if world_cache is not None:
        from bot_world_objects import WorldObjectHit, draw_world_detect_overlay

        world_snap = world_cache.snapshot()
        if world_snap.hits:
            hits = [
                WorldObjectHit(
                    name=h["template"],
                    client_xy=h["client_xy"][:],
                    screen_xy=h["screen_xy"][:],
                    score=float(h["score"]),
                )
                for h in world_snap.hits
            ]
            overlay_bgr = draw_world_detect_overlay(
                overlay_bgr,
                hits,
                inventory_rect=inv_rect,
                search_roi=world_snap.search_roi,
            )

    preview = _resize_for_preview(overlay_bgr, max_width=mw)
    data = _encode_jpeg(preview, quality=quality)
    if data:
        publisher.publish("inventory_overlay", data)


class FramePublisher:
    """Holds latest JPEG bytes per logical stream key."""

    STREAM_KEYS = (
        "world_masked",
        "inventory",
        "inventory_overlay",
        "pristine_client",
        "action_strip",
        "chat_strip",
        "playspace",
        "playspace_blobs",
        "game_preview",
    )

    def __init__(self) -> None:
        self._frames: Dict[str, bytes] = {}
        self._meta: Dict[str, Any] = {}
        self._pristine_meta: Dict[str, Any] = {}
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

    def set_pristine_meta(self, meta: Dict[str, Any]) -> None:
        with self._lock:
            self._pristine_meta = dict(meta)

    def get_pristine_meta(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._pristine_meta)

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
            publish_game_preview(self, eyes.curr_client, max_width=preview_max_width())

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
                publish_game_preview(
                    self._publisher, snap.bgr, max_width=preview_max_width()
                )
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


class PerceptionStreamPublisher:
    """
    Publishes pristine ``game_preview`` JPEGs plus ``/meta`` perception data.

    Optional ``inventory_overlay`` JPEG compositing when ``EXODIA_STREAM_BAKED_OVERLAY=1``.
    """

    def __init__(
        self,
        publisher: FramePublisher,
        pipeline: "CapturePipeline",
        inventory_cache: Optional["InventoryPerceptionCache"] = None,
        world_cache: Any = None,
        *,
        fps: float = 0.0,
        max_width: Optional[int] = None,
    ) -> None:
        self._publisher = publisher
        self._pipeline = pipeline
        self._inventory_cache = inventory_cache
        self._world_cache = world_cache
        self._max_width = int(max_width) if max_width is not None else preview_max_width()
        raw = fps if fps > 0 else os.environ.get("EXODIA_STREAM_PUBLISH_FPS", "10")
        try:
            self._fps = max(1.0, float(raw))
        except (TypeError, ValueError):
            self._fps = 10.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="PerceptionStreamPublisher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        interval = 1.0 / self._fps
        while not self._stop.is_set():
            t0 = time.monotonic()
            snap = self._pipeline.buffer.latest_copy()
            meta: Dict[str, Any] = {}

            if snap is not None:
                publish_pristine_client_snapshot(self._publisher, snap.bgr)
                self._publisher.set_pristine_meta(
                    {
                        "capture_seq": snap.seq,
                        "width": snap.bgr.shape[1],
                        "height": snap.bgr.shape[0],
                        "ts": snap.ts,
                        "frame_age_ms": round(snap.age_ms, 1),
                        "source": "stream",
                    }
                )
                native_w = int(snap.bgr.shape[1])
                native_h = int(snap.bgr.shape[0])
                preview_w, preview_h = preview_dimensions(
                    native_w, native_h, self._max_width
                )
                publish_game_preview(
                    self._publisher, snap.bgr, max_width=self._max_width
                )
                meta = {
                    "capture_seq": snap.seq,
                    "client_rect": list(snap.client_rect),
                    "capture_fps": self._pipeline.capture_fps,
                    "ts": snap.ts,
                    "frame_age_ms": round(snap.age_ms, 1),
                    "overlay_max_width": self._max_width,
                    "frame_width": native_w,
                    "frame_height": native_h,
                    "preview_width": preview_w,
                    "preview_height": preview_h,
                }

            inv_cache = self._inventory_cache
            if inv_cache is not None:
                if _baked_overlay_enabled():
                    if snap is not None:
                        publish_inventory_overlay_live(
                            self._publisher,
                            snap.bgr,
                            inv_cache,
                            world_cache=self._world_cache,
                            max_width=self._max_width,
                        )
                    else:
                        overlay = inv_cache.overlay_jpeg()
                        if overlay:
                            self._publisher.publish("inventory_overlay", overlay)
                inv_snap = inv_cache.snapshot()
                world_cache = self._world_cache
                meta["perception"] = {
                    "inventory": inv_cache.inventory_meta(),
                    "world": world_cache.world_meta() if world_cache is not None else {},
                }
                meta["processed_seq"] = inv_snap.processed_seq
                meta["vision_fps"] = inv_snap.vision_fps
                if snap is not None:
                    meta["seq_lag"] = snap.seq - inv_snap.processed_seq
            else:
                pcache = self._pipeline.cache.snapshot()
                meta.update(
                    {
                        "processed_seq": pcache.processed_seq,
                        "seq_lag": (snap.seq - pcache.processed_seq) if snap else 0,
                        "track_count": pcache.track_count,
                        "motion_magnitude": pcache.motion_magnitude,
                        "vision_fps": self._pipeline.vision_fps,
                    }
                )

            if meta:
                self._publisher.set_meta(meta)

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
                body += "/meta\n/snapshot/meta.json\n/snapshot/pristine_meta.json\n"
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

            if path == "/snapshot/pristine_meta.json":
                pristine_meta = publisher.get_pristine_meta()
                if not pristine_meta:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(pristine_meta, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
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
        perception_publisher: Optional[PerceptionStreamPublisher] = None,
    ) -> None:
        self.port = port
        self.host = host
        self.publisher = publisher if publisher is not None else FramePublisher()
        self.stream_publisher = stream_publisher
        self.perception_publisher = perception_publisher
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
        if self.perception_publisher is not None:
            self.perception_publisher.start()
        handler = _make_handler(self.publisher)
        self._httpd = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.stream_publisher is not None:
            self.stream_publisher.stop()
        if self.perception_publisher is not None:
            self.perception_publisher.stop()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
        self._thread = None

    @property
    def base_url(self) -> str:
        return "http://%s:%d" % (self.host, self.port)
