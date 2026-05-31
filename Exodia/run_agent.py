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
import threading
import time
from pathlib import Path

import bot_legs as Legs
from bot_action_log import ActionLogger, make_run_id
from bot_calibration import run_calibration
from bot_harness import HarnessStepper, create_harness
from bot_perception_status import perception_status_from_eyes
from bot_runtime import RuntimeBridge, RuntimeCommand, set_active_bridge
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


def _env_runtime_default() -> bool:
    raw = os.environ.get("EXODIA_RUNTIME", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _build_runtime_bridge(
    harness,
    stepper: HarnessStepper,
    *,
    enabled: bool,
    brain_name: str,
    spec_paths: list[Path],
) -> RuntimeBridge:
    bridge = RuntimeBridge(
        script_name="run_agent",
        enabled=enabled,
        poll_interval_s=float(os.environ.get("EXODIA_RUNTIME_POLL_S", "0.5")),
    )
    stop_event = threading.Event()

    def _stop(_cmd: RuntimeCommand) -> str:
        stop_event.set()
        bridge.stop_reason = "user stop"
        return "stop requested"

    def _pause(_cmd: RuntimeCommand) -> str:
        bridge.paused = True
        return "paused — write resume to continue"

    def _resume(_cmd: RuntimeCommand) -> str:
        bridge.paused = False
        return "resumed"

    def _health(_cmd: RuntimeCommand) -> str:
        results = bridge.run_health()
        return "health OK (%d probe(s))" % len(results)

    bridge.register("stop", _stop)
    bridge.register("pause", _pause)
    bridge.register("resume", _resume)
    bridge.register("health", _health)
    bridge.register_health_probe(
        lambda: {
            "brain": brain_name,
            "tick": harness._tick,
            "inventory_calibrated": bool(
                (harness.eyes.perception_envelope or {}).get("inventory_rect_client_local")
            ),
        }
    )

    def _runtime_status_payload() -> None:
        bridge.merge_context(
            brain=brain_name,
            tick=harness._tick,
            paused=bridge.paused,
            spec_files=[str(p) for p in spec_paths],
        )
        if stepper.last_result is not None:
            obs = stepper.last_result.observation
            bridge.merge_context(
                action_code=obs.action_text_code,
                skipped_agent=stepper.last_result.skipped_agent,
            )
        bridge.publish_status(perception_status_from_eyes(harness.eyes))

    bridge._agent_status_payload = _runtime_status_payload  # type: ignore[attr-defined]
    bridge._agent_stop_event = stop_event  # type: ignore[attr-defined]
    return bridge


def _run_agent_loop(legs: Legs.BotLegs, stepper: HarnessStepper, runtime: RuntimeBridge, max_ms: int) -> None:
    stop_event = getattr(runtime, "_agent_stop_event", threading.Event())
    status_payload = getattr(runtime, "_agent_status_payload", None)
    start = time.monotonic()
    last_cycle = start
    legs.update_all()

    while True:
        if stop_event.is_set() or legs.flag:
            break
        elapsed_ms = (time.monotonic() - start) * 1000.0
        if max_ms > 0 and elapsed_ms >= max_ms:
            print("Reached --max-ms %d — stopping." % max_ms)
            break

        for line in runtime.poll():
            print("[runtime] %s" % line)

        runtime.wait_while_paused(stop_event.is_set, time.sleep)

        if status_payload is not None:
            status_payload()

        now = time.monotonic()
        since_last_ms = (now - last_cycle) * 1000.0
        if since_last_ms >= legs._t:
            legs.update_all()
            legs.run_tasks()
            last_cycle = now
        else:
            time.sleep(0.005)


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
    p.add_argument(
        "--no-runtime-control",
        action="store_true",
        help="Disable runtime_control.json / runtime_status.json polling",
    )
    p.add_argument(
        "--spec",
        action="append",
        default=[],
        metavar="PATH",
        help="Markdown task spec file (repeatable). Agent reads these to understand the task.",
    )
    args = p.parse_args(argv)

    spec_paths = [Path(p).expanduser().resolve() for p in (args.spec or [])]
    spec_paths = [p for p in spec_paths if str(p)]
    for spec_path in spec_paths:
        if not spec_path.is_file():
            print("ERROR: spec file not found:", spec_path, file=sys.stderr)
            return 1
        if spec_path.suffix.lower() != ".md":
            print("ERROR: spec must be a markdown (.md) file:", spec_path, file=sys.stderr)
            return 1

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

    # Local GDI capture + MJPEG publisher only when this process owns the stream.
    # When EXODIA_STREAM_PORT points at exodia_perception_stream.py (--stream-port 0),
    # consume frames over HTTP and do not compete for port 8765 or spawn wsl_ps.
    publish_stream = args.stream_port > 0
    if publish_stream and capture_stream_enabled(args.stream_port) and report.client_rect:
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
    elif not publish_stream and report.client_rect:
        from bot_capture import stream_service_port

        port = stream_service_port()
        if port > 0:
            print("Using shared perception stream on port %d (no local capture publisher)" % port)

    if publish_stream:
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
    if spec_paths:
        print("Task specs (%d):" % len(spec_paths))
        for spec_path in spec_paths:
            print("  -", spec_path)
            try:
                preview = spec_path.read_text(encoding="utf-8").strip().splitlines()
                for line in preview[:3]:
                    print("    |", line[:120])
                if len(preview) > 3:
                    print("    | … (%d more lines)" % (len(preview) - 3))
            except OSError as exc:
                print("    | (could not read: %s)" % exc)

    stepper = HarnessStepper(harness)
    legs = Legs.BotLegs(mods=[harness.client, harness.eyes])
    legs._t = args.tick_ms
    if args.max_ms > 0:
        legs._max = args.max_ms

    runtime_enabled = not args.no_runtime_control and _env_runtime_default()
    runtime = _build_runtime_bridge(
        harness,
        stepper,
        enabled=runtime_enabled,
        brain_name=brain_name,
        spec_paths=spec_paths,
    )
    set_active_bridge(runtime)
    if runtime.enabled:
        print(runtime.control_help())
    else:
        print("Runtime control disabled (--no-runtime-control or EXODIA_RUNTIME=0).")

    legs.add_task(stepper, "tick", [])

    try:
        _run_agent_loop(legs, stepper, runtime, args.max_ms)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        if stream is not None:
            stream.stop()
        stop_capture_pipeline()
        set_active_bridge(None)
        logger.close(run_meta={
            "brain": brain_name,
            "stream_port": args.stream_port if args.stream_port > 0 else None,
        })

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
