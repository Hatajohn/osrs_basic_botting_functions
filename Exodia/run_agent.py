#!/usr/bin/env python3
"""
Canonical entrypoint for the Exodia agent harness.

Runs a tick-aligned ``BotLegs`` loop with ``ExodiaHarness``, always-on action logging,
and optional MJPEG streaming + session sidecars.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import bot_legs as Legs
from bot_action_log import ActionLogger, make_run_id
from bot_calibration import run_calibration
from bot_harness import HarnessStepper, create_harness
from bot_session import SessionRecorder
from bot_stream import CaptureStreamPublisher, MJPEGStreamServer
from bot_capture import (
    capture_stream_enabled,
    default_capture_fps,
    start_capture_pipeline,
    stop_capture_pipeline,
)
from bot_client_config import load_client_rect


def _load_brain(name: str):
    if name == "reference_fishing":
        from agents.reference_fishing_brain import ReferenceFishingBrain
        return ReferenceFishingBrain(), name
    if name == "idle":
        from bot_harness import IdleBrain
        return IdleBrain(), name
    raise ValueError("Unknown brain: %r (try reference_fishing or idle)" % name)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run Exodia agent harness.")
    p.add_argument(
        "--brain",
        default="reference_fishing",
        help="BotBrain to use (default: reference_fishing)",
    )
    p.add_argument("--session", action="store_true", help="Write per-tick PNG sidecars to sessions/")
    p.add_argument(
        "--stream-port",
        type=int,
        default=int(os.environ.get("EXODIA_STREAM_PORT", "8765") or "8765"),
        help="MJPEG HTTP port (0=disabled). Default: 8765 or EXODIA_STREAM_PORT",
    )
    p.add_argument(
        "--log-dir",
        default=os.environ.get("EXODIA_LOG_DIR", "logs"),
        help="Action log root directory (default: logs or EXODIA_LOG_DIR)",
    )
    p.add_argument(
        "--tick-ms",
        type=int,
        default=600,
        help="Loop interval in ms (default: 600 = OSRS tick)",
    )
    p.add_argument("--debug", action="store_true", help="Enable BotEyes debug mode")
    p.add_argument(
        "--max-ms",
        type=int,
        default=0,
        help="Optional wall-clock cap in ms (0=unlimited)",
    )
    args = p.parse_args(argv)

    run_id = make_run_id()
    log_dir = Path(args.log_dir)
    logger = ActionLogger(run_id, root=log_dir)

    brain, brain_name = _load_brain(args.brain)
    recorder = SessionRecorder(run_id) if args.session else None

    stream: MJPEGStreamServer | None = None
    publisher = None
    stream_pub: CaptureStreamPublisher | None = None
    capture_pipeline = None

    win_rect = load_client_rect()

    harness = create_harness(
        DEBUG=args.debug,
        brain=brain,
        enable_significance_gate=False,
        action_logger=logger,
        frame_publisher=None,
        session_recorder=recorder,
        win_rect=win_rect,
    )

    report = run_calibration(harness.client, harness.eyes)
    print("Calibration backend:", report.capture_backend)
    print("Client rect:", report.client_rect)
    if report.warnings:
        for w in report.warnings:
            print("WARN:", w)
    if report.errors:
        for e in report.errors:
            print("ERROR:", e, file=sys.stderr)
        if not report.ok:
            logger.close(run_meta={"brain": brain_name, "error": "calibration_failed"})
            return 1

    if capture_stream_enabled(args.stream_port) and report.client_rect:
        capture_pipeline = start_capture_pipeline(
            report.client_rect,
            fps=default_capture_fps(),
        )
        inv = harness.eyes.inventory_rect
        chat = harness.eyes.chat_rect
        capture_pipeline.set_geometry(
            report.client_rect,
            inventory_rect=list(inv) if inv else None,
            chat_rect=list(chat) if chat else None,
        )
        harness.capture_pipeline = capture_pipeline
        print("Capture pipeline: %.1f FPS target (2× OSRS tick min)" % default_capture_fps())

    if args.stream_port > 0:
        from bot_stream import FramePublisher

        publisher = FramePublisher()
        if capture_pipeline is not None:
            stream_pub = CaptureStreamPublisher(publisher, capture_pipeline)
        stream = MJPEGStreamServer(
            port=args.stream_port,
            publisher=publisher,
            stream_publisher=stream_pub,
        )
        harness.frame_publisher = publisher
        stream.start_daemon()
        print("MJPEG stream:", stream.base_url)

    print("Action log:", logger.jsonl_path)

    stepper = HarnessStepper(harness)
    legs = Legs.BotLegs(mods=[harness.client, harness.eyes])
    legs._t = args.tick_ms
    if args.max_ms > 0:
        legs._max = args.max_ms
    legs.add_task(stepper, "tick", [])

    try:
        legs.bot_loop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        if stream is not None:
            stream.stop()
        stop_capture_pipeline()
        logger.close(run_meta={
            "brain": brain_name,
            "stream_port": args.stream_port if args.stream_port > 0 else None,
        })

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
