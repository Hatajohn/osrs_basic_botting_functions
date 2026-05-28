#!/usr/bin/env python3
"""
Standalone perception stream — live inventory overlay MJPEG without a bot.

Spawned by ExodiaBotUI on launch when ``client_rect.json`` exists. Prints a JSON
handshake line to stdout for Electron:

  {"ok": true, "url": "http://127.0.0.1:8765", "port": 8765}

Usage:
  python exodia_perception_stream.py --port 8765
  python exodia_perception_stream.py --capture-fps 10 --vision-fps 10 --max-width 640
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

from bot_capture import start_capture_pipeline, stop_capture_pipeline
from bot_client_config import default_client_rect_path, load_client_rect
from bot_inventory_vision import InventoryPerceptionCache, InventoryVisionProcessor
from bot_stream import FramePublisher, MJPEGStreamServer, PerceptionStreamPublisher, preview_max_width
from bot_world_vision import WorldPerceptionCache, WorldVisionProcessor

_CONTROL_FILE = _EXODIA / "captures" / "perception_stream_control.json"
_shutdown = False
_runtime: dict = {}


def _shutdown_runtime() -> None:
    """Stop HTTP, vision, capture, and WSL PowerShell session (SIGTERM / fast exit)."""
    global _shutdown
    _shutdown = True
    srv = _runtime.get("server")
    if srv is not None:
        try:
            srv.stop()
        except Exception:
            pass
    for key in ("inv_vision", "world_vision"):
        proc = _runtime.get(key)
        if proc is not None:
            try:
                proc.stop()
            except Exception:
                pass
    pipe = _runtime.get("pipe")
    if pipe is not None:
        try:
            pipe.stop()
        except Exception:
            pass
    try:
        stop_capture_pipeline()
    except Exception:
        pass
    _runtime.clear()


def _on_signal(_signum: int, _frame: object) -> None:
    _shutdown_runtime()


def _ensure_capture_env() -> None:
    os.chdir(_EXODIA)
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file() and not os.environ.get("EXODIA_CAPTURE_BACKEND"):
        os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
    os.environ.setdefault("EXODIA_CAPTURE_STREAM", "1")
    os.environ.setdefault("EXODIA_INV_FRAME_BUCKETS", "1")


def _emit(obj: dict) -> None:
    print(json.dumps(obj, separators=(",", ":")), flush=True)


def _write_control_template() -> None:
    _CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _CONTROL_FILE.is_file():
        _CONTROL_FILE.write_text(json.dumps({"invalidate": False}, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    global _shutdown

    _ensure_capture_env()

    p = argparse.ArgumentParser(description="Exodia perception MJPEG stream (inventory overlay).")
    p.add_argument("--port", type=int, default=8765, help="HTTP port (default 8765)")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    p.add_argument(
        "--capture-fps",
        type=float,
        default=0.0,
        help="Screen capture FPS (0=EXODIA_CAPTURE_FPS or 10)",
    )
    p.add_argument(
        "--vision-fps",
        type=float,
        default=0.0,
        help="Inventory vision FPS (0=EXODIA_INVENTORY_VISION_FPS or 10)",
    )
    p.add_argument(
        "--world-vision-fps",
        type=float,
        default=0.0,
        help="World vision FPS (0=EXODIA_WORLD_VISION_FPS or 10)",
    )
    p.add_argument(
        "--publish-fps",
        type=float,
        default=0.0,
        help="MJPEG publish FPS (0=EXODIA_STREAM_PUBLISH_FPS or 10)",
    )
    p.add_argument(
        "--max-width",
        type=int,
        default=None,
        help="Overlay / game_preview max width px (default EXODIA_DEBUG_FRAME_MAX_WIDTH or 640)",
    )
    p.add_argument(
        "--control-file",
        default="",
        help="JSON control file path (default captures/perception_stream_control.json)",
    )
    args = p.parse_args(argv)

    rect = load_client_rect()
    if not rect:
        _emit(
            {
                "ok": False,
                "error": "missing client_rect.json",
                "hint": "run calibrate_client_rect.py",
                "client_rect_file": str(default_client_rect_path()),
            }
        )
        return 2

    capture_fps = args.capture_fps if args.capture_fps > 0 else 0.0
    if capture_fps <= 0:
        raw_cap = os.environ.get("EXODIA_CAPTURE_FPS", "10").strip()
        try:
            capture_fps = float(raw_cap)
        except ValueError:
            capture_fps = 10.0
    capture_fps = max(1.0, min(30.0, capture_fps))

    vision_fps = args.vision_fps if args.vision_fps > 0 else 0.0
    world_vision_fps = args.world_vision_fps if args.world_vision_fps > 0 else 0.0
    publish_fps = args.publish_fps if args.publish_fps > 0 else 0.0
    max_width = preview_max_width() if args.max_width is None else int(args.max_width)

    control_path = Path(args.control_file).expanduser() if args.control_file else _CONTROL_FILE
    _write_control_template()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    stop_capture_pipeline()
    pipe = start_capture_pipeline(rect, fps=capture_fps, track_vision=False)
    pipe.set_geometry(rect, None, [0, rect[3] - 30, 520, 30])

    inv_cache = InventoryPerceptionCache()
    inv_vision = InventoryVisionProcessor(
        pipe.buffer,
        inv_cache,
        fps=vision_fps if vision_fps > 0 else None,
        max_overlay_width=max_width,
        control_file=control_path,
    )
    inv_vision.start()

    world_cache = WorldPerceptionCache()
    world_vision = WorldVisionProcessor(
        pipe.buffer,
        inv_cache,
        world_cache,
        rect,
        fps=world_vision_fps if world_vision_fps > 0 else None,
        control_file=control_path,
    )
    world_vision.start()

    publisher = FramePublisher()
    stream_pub = PerceptionStreamPublisher(
        publisher,
        pipe,
        inv_cache,
        world_cache=world_cache,
        fps=publish_fps if publish_fps > 0 else 0.0,
        max_width=max_width,
    )
    server = MJPEGStreamServer(
        port=args.port,
        host=args.host,
        publisher=publisher,
        perception_publisher=stream_pub,
    )
    _runtime["server"] = server
    _runtime["inv_vision"] = inv_vision
    _runtime["world_vision"] = world_vision
    _runtime["pipe"] = pipe
    server.start_daemon()

    base = server.base_url
    _emit({"ok": True, "url": base, "port": args.port, "capture_fps": capture_fps})

    try:
        while not _shutdown:
            time.sleep(0.05)
    except KeyboardInterrupt:
        _shutdown_runtime()

    if not _shutdown:
        _shutdown_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
