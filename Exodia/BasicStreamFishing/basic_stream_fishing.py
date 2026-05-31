"""
Basic stream fishing — FISHING, SEEK_SPOT, and CRACKING on the perception stream.

No ``BotEyes`` / ``bot_update``. Signals:
- Green ``Fishing`` in ``tick.text`` (text cache) → fishing.
- World template tracks → spot clicks.
- Inventory full (0 empty slots) → one hammer→eel, then wait until empty count stabilizes → seek.

Validation target: infernal eel (``osrs_infernalEel``). Requires labeled
``hammer`` and ``infernal_eel`` in ``items/`` for cracking.

TODO: Extract CRACKING step logic from ``basic_stream_fishing_fsm.py`` into a
dedicated module when a second bot needs it.

Run from Exodia (stream service must be up, ``EXODIA_STREAM_PORT`` set)::

    cd Exodia && source exodia/bin/activate
    python -m BasicStreamFishing.basic_stream_fishing

Stop: F8 (``EXODIA_STOP_HOTKEY``) or Ctrl+C.

World spot stems (``images/`` under Botting/ cwd):

  ``EXODIA_INFERNAL_SPOT_TEMPLATES`` — default ``osrs_infernalEel.png,infernal_eel_spot.png``

Session log: ``Exodia/logs/basic_stream_fishing_latest.log``
"""

from __future__ import annotations

import os
import sys
import threading
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

EXODIA_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = EXODIA_DIR / "logs"
SESSION_LOG_FILE = LOGS_DIR / "basic_stream_fishing_latest.log"
EVENTS_LOG_FILE = LOGS_DIR / "basic_stream_fishing_events.jsonl"


def _check_deps() -> None:
    try:
        import cv2  # noqa: F401
    except ImportError:
        print("Missing Python packages (cv2/OpenCV). Use the project venv:", file=sys.stderr)
        print("  cd Exodia && python3 -m venv exodia && source exodia/bin/activate", file=sys.stderr)
        print("  pip install -r requirements-minimal.txt", file=sys.stderr)
        print("  python -m BasicStreamFishing.basic_stream_fishing", file=sys.stderr)
        raise SystemExit(1)

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("Missing python3-tk (required by PyAutoGUI on Linux/WSL).", file=sys.stderr)
        print("  sudo apt-get install -y python3-tk python3-dev", file=sys.stderr)
        raise SystemExit(1)


_check_deps()

if str(EXODIA_DIR) not in sys.path:
    sys.path.insert(0, str(EXODIA_DIR))

from bot_action_ui import ACTION_NO_UI, action_code_label, is_action_fishing
from bot_perception_client import StreamUnavailableError
from bot_perception_types import INV_SLOT_COUNT, PerceptionTick
from bot_runtime import (
    RuntimeBridge,
    RuntimeCommand,
    ensure_logs_dir,
    set_active_bridge,
    write_json_atomic,
)
from bot_session_events import close_session_events, install_session_events, log_event
from bot_stream_context import basic_stream_context_from_init
from bot_stream_control import configure_infernal_world_watchlist, infernal_spot_world_stems
from .basic_stream_fishing_fsm import (
    MAX_SPOT_PAN_ATTEMPTS,
    MAX_SPOT_WALK_ATTEMPTS,
    POST_CLICK_FISH_POLL_S,
    POST_CLICK_FISH_WAIT_S,
    BasicStreamFishingContext,
    BasicStreamFishingMachine,
    BasicStreamFishingState,
    InventorySlotCountError,
    _locate_spots_from_tick,
    configure_fsm,
    initial_state_from_action,
)

STOP_HOTKEY = os.environ.get("EXODIA_STOP_HOTKEY", "f8")
_stop = threading.Event()
_last_spots_visible: int = 0


def _ensure_images_cwd() -> None:
    botting_root = EXODIA_DIR.parent
    images_dir = botting_root / "images"
    if images_dir.is_dir() and os.getcwd() != str(botting_root):
        os.chdir(botting_root)


def _fsm_interval_s() -> float:
    raw = os.environ.get("EXODIA_FSM_INTERVAL_S", "").strip()
    if raw:
        return float(raw)
    return float(os.environ.get("EXODIA_POLL_INTERVAL", "1"))


def _request_stop() -> None:
    _stop.set()
    print("\nStop hotkey pressed (%s) — finishing current cycle..." % STOP_HOTKEY)


def _register_stop_hotkey() -> None:
    try:
        import keyboard  # noqa: PLC0415

        keyboard.add_hotkey(STOP_HOTKEY, _request_stop, suppress=False)
        print("Press %s to stop (or Ctrl+C)." % STOP_HOTKEY.upper())
    except ImportError:
        print("Press Ctrl+C to stop (pip install keyboard for %s hotkey)." % STOP_HOTKEY.upper())
    except Exception as exc:
        print("Hotkey unavailable (%s) — use Ctrl+C to stop." % exc)


def _unregister_stop_hotkey() -> None:
    try:
        import keyboard  # noqa: PLC0415

        keyboard.unhook_all()
    except Exception:
        pass


def _sleep_interruptible(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not _stop.is_set():
        time.sleep(min(0.05, end - time.monotonic()))


def _parse_rect(raw: str) -> list:
    parts = [int(x.strip()) for x in raw.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("Expected LEFT,TOP,WIDTH,HEIGHT")
    return parts


def _list_windows() -> None:
    import window_tool as Wt

    if not Wt.xdotool_available():
        print("xdotool not on PATH — install: sudo apt-get install xdotool")
        return
    rows = Wt.linux_list_visible_windows()
    if not rows:
        print("No visible X11 windows found.")
        return
    print("Visible windows (id | title | geometry):")
    for wid, name in rows:
        geo = Wt.linux_window_geometry(wid)
        geo_s = "%s,%s,%s,%s" % geo if geo else "?, ?, ?, ?"
        print("  %6s | %s | %s" % (wid, name or "(no title)", geo_s))


def _env_runtime_default() -> bool:
    raw = (os.environ.get("EXODIA_RUNTIME", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _enable_wsl_ps_if_available() -> None:
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file():
        os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
        os.environ.setdefault("EXODIA_INPUT_BACKEND", "wsl_ps")


def _resolve_client_rect(args) -> tuple:
    from bot_client_config import default_client_rect_path, load_client_rect, rect_from_env

    if args.rect:
        rect = _parse_rect(args.rect)
        _enable_wsl_ps_if_available()
        return rect, "--rect"

    try:
        env_rect = rect_from_env()
        if env_rect:
            _enable_wsl_ps_if_available()
            return env_rect, "EXODIA_CLIENT_RECT"
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

    file_rect = load_client_rect()
    if file_rect:
        _enable_wsl_ps_if_available()
        print("Loaded client rect from", default_client_rect_path(), ":", file_rect)
        return file_rect, "client_rect.json"

    return None, "xdotool"


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Basic stream fishing bot (infernal seek/fish)")
    p.add_argument("--rect", metavar="L,T,W,H", help="Manual Win32 screen rect")
    p.add_argument(
        "--window-title",
        default=os.environ.get("EXODIA_WINDOW_TITLE", "RuneLite"),
        help="Window title substring (default: RuneLite)",
    )
    p.add_argument("--list-windows", action="store_true", help="Print X11 windows and exit")
    p.add_argument("--calibrate", action="store_true", help="Run calibrate_client_rect.py")
    p.add_argument(
        "--log-file",
        metavar="PATH",
        default=os.environ.get("EXODIA_BASIC_STREAM_FISHING_LOG", "").strip(),
        help="Session log (default: %s)" % SESSION_LOG_FILE,
    )
    p.add_argument(
        "--max-cycles",
        type=int,
        default=int(os.environ.get("EXODIA_MAX_CYCLES", "0")),
        help="Stop after N FSM steps (0 = unlimited)",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=_fsm_interval_s(),
        help="Seconds between throttled FSM polls (EXODIA_FSM_INTERVAL_S, default 1)",
    )
    p.add_argument("--no-runtime-control", action="store_true")
    return p.parse_args(argv)


def _perception_status_from_tick(tick: PerceptionTick) -> Dict[str, Any]:
    return {
        "perception": {
            "capture_seq": tick.capture_seq,
            "frame_age_ms": round(tick.frame_age_ms, 1),
            "inventory_calibrated": tick.inventory.calibrated,
            "action_code": tick.action.action_code,
            "fishing_visible": tick.action.fishing_visible,
            "not_fishing_visible": tick.action.not_fishing_visible,
            "strip_visible": tick.action.strip_visible,
            "world_track_count": len(tick.world.tracks),
        }
    }


def _save_stream_snapshot(ctx: BasicStreamFishingContext, *, tag: str = "manual") -> Path:
    import cv2

    ensure_logs_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = LOGS_DIR / "diag" / ("%s_%s" % (tag, stamp))
    out.mkdir(parents=True, exist_ok=True)
    tick, events = ctx.refresh()
    payload = {
        "capture_seq": tick.capture_seq,
        "frame_age_ms": tick.frame_age_ms,
        "client_rect": list(tick.client_rect) if tick.client_rect else None,
        "action": {
            "action_code": tick.action.action_code,
            "fishing_visible": tick.action.fishing_visible,
            "not_fishing_visible": tick.action.not_fishing_visible,
        },
        "inventory": {
            "calibrated": tick.inventory.calibrated,
            "occupied": tick.inventory.occupied,
        },
        "world": {
            "track_count": len(tick.world.tracks),
            "templates_scanned": list(tick.world.templates_scanned),
        },
        "events": [getattr(e, "kind", type(e).__name__) for e in events],
    }
    write_json_atomic(out / "tick.json", payload)
    try:
        bgr = ctx.stream.perception.pristine_frame()
        if bgr is not None and bgr.size > 0:
            cv2.imwrite(str(out / "client.png"), bgr)
    except StreamUnavailableError:
        pass
    return out


def _build_runtime_bridge(
    ctx: BasicStreamFishingContext,
    machine: BasicStreamFishingMachine,
    *,
    enabled: bool,
) -> RuntimeBridge:
    bridge = ctx.stream.runtime
    bridge.enabled = enabled
    bridge.script_name = "basic_stream_fishing"
    bridge.poll_interval_s = float(os.environ.get("EXODIA_RUNTIME_POLL_S", "0.5"))

    def _stop(_cmd: RuntimeCommand) -> str:
        _request_stop()
        return "stop requested"

    def _pause(_cmd: RuntimeCommand) -> str:
        bridge.paused = True
        return "paused"

    def _resume(_cmd: RuntimeCommand) -> str:
        bridge.paused = False
        return "resumed"

    def _snapshot(_cmd: RuntimeCommand) -> str:
        tag = str(_cmd.args.get("tag") or "manual")
        out = _save_stream_snapshot(ctx, tag=tag)
        return "snapshot saved -> %s" % out

    def _refresh(_cmd: RuntimeCommand) -> str:
        ctx.refresh()
        return "refreshed (action=%s)" % action_code_label(ctx.action_code)

    def _step(_cmd: RuntimeCommand) -> str:
        bridge.force_step = True
        return "one FSM step queued"

    def _pan_left(_cmd: RuntimeCommand) -> str:
        center = ctx.global_center()
        rect = ctx.client_rect()
        if center is None or rect is None:
            return "no client rect"
        ctx.stream.arms.pan_left(
            center=center,
            win_rect=rect,
            rand=bool(_cmd.args.get("rand", True)),
        )
        return "panned left"

    def _pan_right(_cmd: RuntimeCommand) -> str:
        center = ctx.global_center()
        rect = ctx.client_rect()
        if center is None or rect is None:
            return "no client rect"
        ctx.stream.arms.pan_right(
            center=center,
            win_rect=rect,
            rand=bool(_cmd.args.get("rand", True)),
        )
        return "panned right"

    def _set_state(cmd: RuntimeCommand) -> str:
        name = str(cmd.args.get("state") or cmd.args.get("name") or "").strip().upper()
        if not name:
            raise ValueError("set_state requires args.state (FISHING, SEEK_SPOT, CRACKING)")
        ctx.state = BasicStreamFishingState[name]
        return "state set to %s" % ctx.state.name

    bridge.register("stop", _stop)
    bridge.register("pause", _pause)
    bridge.register("resume", _resume)
    bridge.register("snapshot", _snapshot)
    bridge.register("refresh", _refresh)
    bridge.register("step", _step)
    bridge.register("pan_left", _pan_left)
    bridge.register("pan_right", _pan_right)
    bridge.register("set_state", _set_state)

    def _health(_cmd: RuntimeCommand) -> str:
        results = bridge.run_health()
        return "health OK (%d probe(s))" % len(results)

    bridge.register("health", _health)
    return bridge


def _action_text_health_lines(action) -> list:
    """Printable health lines for OCR action metadata when present on the tick."""
    lines = []
    if getattr(action, "action_line_text", None):
        lines.append("Health: action_line_text → %r" % action.action_line_text)
    if getattr(action, "detection_source", None):
        lines.append("Health: detection_source → %s" % action.detection_source)
    return lines


def _stream_health_probe(ctx: BasicStreamFishingContext) -> dict:
    global _last_spots_visible
    tick, _ = ctx.refresh()
    stems = infernal_spot_world_stems()
    spots = _locate_spots_from_tick(tick)
    _last_spots_visible = len(spots)
    templates = {}
    for stem in stems:
        png = Path("images") / ("%s.png" % stem)
        templates[stem] = png.is_file()
    stable_by_stem = {
        stem: len(tick.world.stable_tracks(stem)) for stem in stems
    }
    return {
        "spot_stems": stems,
        "spot_templates": templates,
        "inventory_calibrated": tick.inventory.calibrated,
        "action_code": ctx.action_code,
        "action_line_text": ctx.action_line_text,
        "action_line_color": ctx.action_line_color,
        "detection_source": ctx.action_detection_source,
        "text_span_count": tick.text.span_count,
        "capture_seq": tick.capture_seq,
        "frame_age_ms": tick.frame_age_ms,
        "world_track_count": len(tick.world.tracks),
        "stable_tracks_by_stem": stable_by_stem,
        "spots_visible": _last_spots_visible,
        "crack_started": ctx.crack_started,
    }


def _runtime_status_payload(ctx: BasicStreamFishingContext, runtime: RuntimeBridge) -> None:
    tick = ctx.last_tick
    runtime.merge_context(
        fsm_state=ctx.state.name,
        action_code=ctx.action_code,
        action_label=ctx.action_status_label(),
        action_line_text=ctx.action_line_text,
        action_detection_source=ctx.action_detection_source,
        waiting_for_fish=ctx.waiting_for_fish,
        crack_started=ctx.crack_started,
        spots_visible=_last_spots_visible,
        last_spot_click=ctx.last_spot_click,
        cycles=ctx.cycles,
        capture_seq=tick.capture_seq if tick is not None else None,
        world_track_count=len(tick.world.tracks) if tick is not None else None,
    )
    if tick is not None:
        runtime.publish_status(_perception_status_from_tick(tick))
    else:
        runtime.publish_status({})


def _print_startup_health(ctx: BasicStreamFishingContext) -> None:
    global _last_spots_visible
    tick, _ = ctx.refresh()
    code = ctx.action_code
    hint = " — will seek spot" if not is_action_fishing(code) else ""
    print("Health: action line →", ctx.action_status_label() + hint)
    if ctx.action_detection_source:
        print("Health: action source →", ctx.action_detection_source)
    n_spans = len(tick.text.spans)
    if tick.text.span_count or n_spans:
        print(
            "Health: text spans → parsed %d / meta_count %d (seq %d)"
            % (n_spans, tick.text.span_count, tick.text.seq)
        )
        if tick.text.span_count > 0 and n_spans == 0:
            print(
                "Health: WARN meta has span_count but no spans in tick — "
                "set EXODIA_TEXT_META_FULL=1 or rely on fishing_spans in meta"
            )
    print(
        "Health: stream capture_seq=%d frame_age_ms=%.0f"
        % (tick.capture_seq, tick.frame_age_ms)
    )
    stems = configure_infernal_world_watchlist()
    print("Health: world watchlist stems:", ", ".join(stems))
    for stem in stems:
        path = Path("images") / ("%s.png" % stem)
        print("Health: spot template", stem, "OK" if path.is_file() else "MISSING")
    if tick.inventory.calibrated:
        print("Health: inventory calibrated OK", tick.inventory.rect)
    else:
        print("Health: WARN inventory not calibrated — stream_bot_init will fail")
    spot_hits = _locate_spots_from_tick(tick)
    _last_spots_visible = len(spot_hits)
    print("Health: infernal spots visible now (stream tracks):", _last_spots_visible)
    inv = tick.inventory
    print(
        "Health: inventory %d empty, %d/%d occupied (grid) | meta occupied=%d"
        % (
            inv.empty_slot_count(),
            inv.occupied_from_grid(),
            INV_SLOT_COUNT,
            inv.occupied,
        )
    )
    print(
        "Health: FSM reads → %s (via %s)"
        % (
            ctx.action_status_label(),
            ctx.action_detection_source or "?",
        )
    )
    print(
        "Health: pan attempts %d | walk attempts %d"
        % (MAX_SPOT_PAN_ATTEMPTS, MAX_SPOT_WALK_ATTEMPTS)
    )


def _install_run_logger(path: Optional[Path] = None) -> Path:
    """Tee stdout/stderr to a session log (minimal inline logger)."""
    from InfernalEelFishing.infernal_eel_log import close_run_logger, install_run_logger

    target = path or SESSION_LOG_FILE
    return install_run_logger(target)


def _close_run_logger() -> None:
    from InfernalEelFishing.infernal_eel_log import close_run_logger

    close_run_logger()


def _run_basic_stream_session(args) -> None:
    win_rect, rect_source = _resolve_client_rect(args)
    if rect_source != "xdotool":
        print("Window mode:", rect_source)
        print("Capture:", os.environ.get("EXODIA_CAPTURE_BACKEND", "stream"))
        print("Input:", os.environ.get("EXODIA_INPUT_BACKEND", "pyautogui"))

    if win_rect is None:
        print(
            "Stream bots require a calibrated client rect.",
            file=sys.stderr,
        )
        print("  python calibrate_client_rect.py", file=sys.stderr)
        print("  python -m BasicStreamFishing.basic_stream_fishing", file=sys.stderr)
        raise SystemExit(1)

    install_session_events("basic_stream_fishing", path=EVENTS_LOG_FILE)
    log_event("session.start", rect_source=rect_source, max_cycles=args.max_cycles or 0)

    _register_stop_hotkey()
    ctx: Optional[BasicStreamFishingContext] = None
    runtime_enabled = not args.no_runtime_control and _env_runtime_default()
    runtime = RuntimeBridge(
        script_name="basic_stream_fishing",
        enabled=runtime_enabled,
        poll_interval_s=float(os.environ.get("EXODIA_RUNTIME_POLL_S", "0.5")),
    )

    try:
        stream_ctx = basic_stream_context_from_init(
            runtime,
            win_rect=win_rect,
            window_title=args.window_title,
            require_calibration=True,
        )
    except StreamUnavailableError as exc:
        print("Stream unavailable:", exc, file=sys.stderr)
        print("", file=sys.stderr)
        print("Start the perception stream and set EXODIA_STREAM_PORT.", file=sys.stderr)
        print("  EXODIA_CAPTURE_STREAM=1 EXODIA_STREAM_PORT=<port> python exodia_perception_stream.py", file=sys.stderr)
        raise SystemExit(1)

    max_cycles = int(args.max_cycles)
    interval_s = args.interval
    timer_session_ms = int(os.environ.get("EXODIA_SESSION_MS", "6000000"))
    deadline = time.monotonic() + timer_session_ms / 1000.0
    next_cycle = time.monotonic()

    ctx = BasicStreamFishingContext(stream=stream_ctx)
    ctx.refresh()
    ctx.state = initial_state_from_action(ctx.action_code)
    if ctx.state == BasicStreamFishingState.SEEK_SPOT and ctx.action_code == ACTION_NO_UI:
        print("Initial state: SEEK_SPOT (fishing action UI not visible)")
    machine = BasicStreamFishingMachine(ctx)

    _print_startup_health(ctx)

    print("Basic stream fishing FSM — states: FISHING | SEEK_SPOT | CRACKING (text cache + stream)")
    print("  Spot stems: %s" % ", ".join(infernal_spot_world_stems()))
    print("  Poll interval %.1fs (EXODIA_FSM_INTERVAL_S)" % interval_s)
    print(
        "  After spot click: wait up to %.0fs for green fishing UI (poll %.1fs)"
        % (POST_CLICK_FISH_WAIT_S, POST_CLICK_FISH_POLL_S)
    )
    if max_cycles > 0:
        print("  Max FSM steps this run:", max_cycles)
    print("Images cwd:", os.getcwd())
    print("Initial state:", ctx.state.name)

    runtime = _build_runtime_bridge(ctx, machine, enabled=runtime_enabled)
    runtime.register_health_probe(lambda: _stream_health_probe(ctx))
    set_active_bridge(runtime)
    configure_fsm(
        sleep_fn=_sleep_interruptible,
        stop_check=_stop.is_set,
        log_event=log_event,
        set_last_action=runtime.set_last_action,
    )
    if runtime.enabled:
        print(runtime.control_help())
    else:
        print("Runtime control disabled (--no-runtime-control or EXODIA_RUNTIME=0).")

    try:
        while time.monotonic() < deadline and not _stop.is_set():
            for line in runtime.poll():
                print("[runtime] %s" % line)
            _runtime_status_payload(ctx, runtime)

            runtime.wait_while_paused(_stop.is_set, _sleep_interruptible)

            if max_cycles > 0 and ctx.cycles >= max_cycles:
                print("Reached --max-cycles %d — stopping." % max_cycles)
                break

            throttled = machine.should_throttle() and not runtime.force_step
            if throttled:
                now = time.monotonic()
                if now < next_cycle:
                    _sleep_interruptible(min(0.25, next_cycle - now))
                    continue
                next_cycle += interval_s

            runtime.force_step = False
            machine.step()

            if machine.should_throttle():
                tick = ctx.last_tick
                track_n = len(tick.world.tracks) if tick is not None else "?"
                inv_n = (
                    "%d empty"
                    % tick.inventory.empty_slot_count()
                    if tick is not None
                    else "?"
                )
                print(
                    "Cycle %d | %s | action %s | tracks %s | inv %s"
                    % (
                        ctx.cycles,
                        ctx.state.name,
                        action_code_label(ctx.action_code),
                        track_n,
                        inv_n,
                    )
                )
    except KeyboardInterrupt:
        print("\nCtrl+C — stopping.")
    except InventorySlotCountError as exc:
        _stop.set()
        print("\nInventory slot count error — stopping bot:", exc, file=sys.stderr)
        log_event("session.error", error="inventory_slot_count", detail=str(exc))
    except StreamUnavailableError as exc:
        print("\nStream lost:", exc)
    finally:
        set_active_bridge(None)
        _unregister_stop_hotkey()
        if ctx is not None:
            print(
                "Stopped after %d steps (final state: %s)."
                % (ctx.cycles, ctx.state.name)
            )
            close_session_events(
                {
                    "cycles": ctx.cycles,
                    "fsm_state": ctx.state.name,
                    "action_code": ctx.action_code,
                    "crack_started": ctx.crack_started,
                    "stopped": _stop.is_set(),
                }
            )
        else:
            close_session_events({"stopped": True})


if __name__ == "__main__":
    _ensure_images_cwd()
    args = _parse_args()

    if args.list_windows:
        _list_windows()
        raise SystemExit(0)

    if args.calibrate:
        import calibrate_client_rect

        raise SystemExit(calibrate_client_rect.main())

    _install_run_logger(Path(args.log_file) if args.log_file else None)

    try:
        _run_basic_stream_session(args)
    finally:
        _close_run_logger()
