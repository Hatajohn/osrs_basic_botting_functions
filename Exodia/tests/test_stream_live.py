#!/usr/bin/env python3
"""
Live test for decoupled capture + MJPEG (game must be visible to wsl_ps).

Uses ``client_rect.json`` (Win32 coords). Example:

  cd Exodia
  export EXODIA_CAPTURE_BACKEND=wsl_ps
  python tests/test_stream_live.py --seconds 30

Open in browser (from Windows host if WSL):
  http://127.0.0.1:8765/stream/playspace_blobs
  http://127.0.0.1:8765/meta
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from bot_capture import (
    default_capture_fps,
    start_capture_pipeline,
    stop_capture_pipeline,
)
from bot_client_config import load_client_rect
from bot_stream import CaptureStreamPublisher, FramePublisher, MJPEGStreamServer


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    os.environ.setdefault("EXODIA_CAPTURE_STREAM", "1")

    p = argparse.ArgumentParser(description="Live streaming capture test.")
    p.add_argument("--seconds", type=int, default=30, help="How long to run (default 30)")
    p.add_argument("--port", type=int, default=8765, help="MJPEG HTTP port")
    p.add_argument("--fps", type=float, default=0.0, help="Capture FPS (0=default 4)")
    args = p.parse_args(argv)

    rect = load_client_rect()
    if not rect:
        print("Missing client_rect.json — run: python calibrate_client_rect.py", file=sys.stderr)
        return 2

    fps = args.fps if args.fps > 0 else default_capture_fps()
    print("client_rect:", rect)
    print("capture_fps target:", fps)
    print("backend:", os.environ.get("EXODIA_CAPTURE_BACKEND"))

    stop_capture_pipeline()
    pipe = start_capture_pipeline(rect, fps=fps)
    pipe.set_geometry(rect, None, [0, rect[3] - 30, 520, 30])

    publisher = FramePublisher()
    stream_pub = CaptureStreamPublisher(publisher, pipe)
    mjpeg = MJPEGStreamServer(
        port=args.port,
        publisher=publisher,
        stream_publisher=stream_pub,
    )
    mjpeg.start_daemon()
    base = mjpeg.base_url
    print("MJPEG:", base)
    print("  playspace_blobs -> %s/stream/playspace_blobs" % base)
    print("  meta            -> %s/meta" % base)
    print("\nMove the camera or walk an NPC — sampling...\n")

    last_seq = 0
    t_end = time.monotonic() + max(1, args.seconds)
    try:
        while time.monotonic() < t_end:
            time.sleep(1.0)
            ps = pipe.cache.snapshot()
            seq = pipe.buffer.seq
            delta = seq - last_seq
            last_seq = seq
            snap = pipe.buffer.latest_copy()
            mean = float(snap.bgr.mean()) if snap else 0.0
            print(
                "seq=%3d +%d/s lag=%2d tracks=%2d motion=%5.1f cap_fps=%4.1f vis_fps=%4.1f mean=%3.0f"
                % (
                    seq,
                    delta,
                    seq - ps.processed_seq,
                    ps.track_count,
                    ps.motion_magnitude,
                    pipe.capture_fps,
                    pipe.vision_fps,
                    mean,
                )
            )
    except KeyboardInterrupt:
        print("\nInterrupted.")

    try:
        meta = json.loads(
            urllib.request.urlopen("%s/meta" % base, timeout=2).read().decode("utf-8")
        )
        print("\n/meta:", json.dumps(meta, indent=2))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print("\n/meta fetch failed:", exc)

    mjpeg.stop()
    stop_capture_pipeline()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
