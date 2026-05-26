"""
Infernal eel fishing entrypoint: FSM session loop with runtime bridge and logging.

Use this when you need to run infernal eel fishing (fish at spots, crack with Imcando hammer at 28/28).

Labeled inventory items (via label_inventory_item.py → items/):
  infernal_eel — eel icon for bucket counting + use-on target
  hammer — Imcando hammer for cracking

World spot templates (images/ under Botting/ cwd):
  infernal_eel_spot.png (default; override EXODIA_INFERNAL_SPOT_TEMPLATES)

Run from Exodia:
  cd Exodia && source exodia/bin/activate && python -m InfernalEelFishing.infernal_eel_fishing
  — or — ./InfernalEelFishing/run_infernal_eel.sh

Session log: Exodia/logs/infernal_eel_latest.log
Stop: F8 (EXODIA_STOP_HOTKEY) or Ctrl+C
"""

import os
import sys
import threading
import time
import argparse
from pathlib import Path
from typing import Optional

def _check_deps() -> None:
    try:
        import cv2  # noqa: F401
    except ImportError:
        print("Missing Python packages (cv2/OpenCV). Use the project venv:", file=sys.stderr)
        print("  cd Exodia && python3 -m venv exodia && source exodia/bin/activate", file=sys.stderr)
        print("  pip install -r requirements-minimal.txt", file=sys.stderr)
        print("  python -m InfernalEelFishing.infernal_eel_fishing", file=sys.stderr)
        raise SystemExit(1)

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("Missing python3-tk (required by PyAutoGUI on Linux/WSL).", file=sys.stderr)
        print("  sudo apt-get install -y python3-tk python3-dev", file=sys.stderr)
        raise SystemExit(1)


_check_deps()

_EXODIA_DIR = Path(__file__).resolve().parent.parent
if str(_EXODIA_DIR) not in sys.path:
    sys.path.insert(0, str(_EXODIA_DIR))

import bot_actions as Actions
import bot_client as Client
import bot_eyes as Eyes
from bot_action_ui import action_code_label, is_action_fishing
from bot_gamestate import inventory_is_full
from bot_inventory_detect import bind_inventory_to_eyes
from bot_inventory_items import count_labeled_item_slots, read_inventory_labels
from bot_perception_status import perception_status_from_eyes
from bot_runtime import (
    RuntimeBridge,
    RuntimeCommand,
    save_perception_snapshot,
    set_active_bridge,
)
from bot_session_events import close_session_events, install_session_events, log_event
from .infernal_eel_fsm import (
    CRACK_TICK_DELAY_S,
    EEL_ITEM_NAME,
    HAMMER_ITEM_NAME,
    INV_SLOT_COUNT,
    POST_CLICK_FISH_POLL_S,
    POST_CLICK_FISH_WAIT_S,
    SPOT_TEMPLATES,
    InfernalEelContext,
    InfernalEelMachine,
    InfernalEelState,
    _locate_spots,
    _save_stagnation_snapshot,
    configure_fsm,
)
from .infernal_eel_log import (
    EVENTS_LOG_FILE,
    LOGS_DIR,
    SESSION_LOG_FILE,
    close_run_logger,
    install_run_logger,
)

STOP_HOTKEY = os.environ.get("EXODIA_STOP_HOTKEY", "f8")
_stop = threading.Event()
_last_spots_visible: int = 0


def _ensure_images_cwd() -> None:
    exodia_dir = Path(__file__).resolve().parent.parent
    botting_root = exodia_dir.parent
    images_dir = botting_root / "images"
    if images_dir.is_dir() and os.getcwd() != str(botting_root):
        os.chdir(botting_root)


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
    p = argparse.ArgumentParser(description="Infernal eel fishing bot")
    p.add_argument("--rect", metavar="L,T,W,H", help="Manual Win32 screen rect")
    p.add_argument(
        "--window-title",
        default=os.environ.get("EXODIA_WINDOW_TITLE", "RuneLite"),
        help="Window title substring (default: RuneLite)",
    )
    p.add_argument("--list-windows", action="store_true", help="Print X11 windows and exit")
    p.add_argument("--calibrate", action="store_true", help="Run calibrate_client_rect.py")
    p.add_argument("--diagnose", action="store_true", help="One-shot perception check; no clicks")
    p.add_argument(
        "--log-file",
        metavar="PATH",
        default=os.environ.get("EXODIA_INFERNAL_EEL_LOG", "").strip(),
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
        default=float(os.environ.get("EXODIA_POLL_INTERVAL", "6")),
        help="Seconds between throttled polls (default 6)",
    )
    p.add_argument("--no-runtime-control", action="store_true")
    p.add_argument("--overlay", action="store_true", help="Live debug overlay")
    return p.parse_args(argv)


def _build_runtime_bridge(ctx: InfernalEelContext, machine: InfernalEelMachine, *, enabled: bool) -> RuntimeBridge:
    bridge = RuntimeBridge(
        script_name="infernal_eel_fishing",
        enabled=enabled,
        poll_interval_s=float(os.environ.get("EXODIA_RUNTIME_POLL_S", "0.5")),
    )

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
        out = save_perception_snapshot(ctx.bot_e, tag=tag)
        return "snapshot saved -> %s" % out

    def _refresh(_cmd: RuntimeCommand) -> str:
        Actions.bot_update(ctx.client, ctx.bot_e)
        ctx.action_code = ctx.bot_e.get_action_text(refresh=False)
        return "refreshed (action=%s)" % action_code_label(ctx.action_code)

    def _step(_cmd: RuntimeCommand) -> str:
        bridge.force_step = True
        return "one FSM step queued"

    def _pan_left(_cmd: RuntimeCommand) -> str:
        ctx.bot_a.pan_left(
            center=ctx.bot_e.global_center,
            win_rect=ctx.bot_e.client_rect,
            rand=bool(_cmd.args.get("rand", True)),
        )
        return "panned left"

    def _pan_right(_cmd: RuntimeCommand) -> str:
        ctx.bot_a.pan_right(
            center=ctx.bot_e.global_center,
            win_rect=ctx.bot_e.client_rect,
            rand=bool(_cmd.args.get("rand", True)),
        )
        return "panned right"

    def _set_state(cmd: RuntimeCommand) -> str:
        name = str(cmd.args.get("state") or cmd.args.get("name") or "").strip().upper()
        if not name:
            raise ValueError("set_state requires args.state (FISHING, SEEK_SPOT, CRACKING)")
        ctx.state = InfernalEelState[name]
        return "state set to %s" % ctx.state.name

    def _stagnation_snapshot(_cmd: RuntimeCommand) -> str:
        _save_stagnation_snapshot(ctx)
        return "stagnation snapshot saved"

    bridge.register("stop", _stop)
    bridge.register("pause", _pause)
    bridge.register("resume", _resume)
    bridge.register("snapshot", _snapshot)
    bridge.register("refresh", _refresh)
    bridge.register("step", _step)
    bridge.register("pan_left", _pan_left)
    bridge.register("pan_right", _pan_right)
    bridge.register("set_state", _set_state)
    bridge.register("stagnation_snapshot", _stagnation_snapshot)

    def _health(_cmd: RuntimeCommand) -> str:
        results = bridge.run_health()
        return "health OK (%d probe(s))" % len(results)

    bridge.register("health", _health)
    return bridge


def _eel_health_probe(ctx: InfernalEelContext) -> dict:
    bot_e = ctx.bot_e
    slot_items, occ = read_inventory_labels(bot_e)
    return {
        "items_labeled": {
            EEL_ITEM_NAME: (Path("items") / ("%s.png" % EEL_ITEM_NAME)).is_file(),
            HAMMER_ITEM_NAME: (Path("items") / ("%s.png" % HAMMER_ITEM_NAME)).is_file(),
        },
        "spot_templates": {t: (Path("images") / t).is_file() for t in SPOT_TEMPLATES},
        "inventory_calibrated": bool(bot_e.inventory_rect),
        "action_code": int(bot_e.get_action_text(refresh=False)),
        "eel_slots": count_labeled_item_slots(slot_items, occ, EEL_ITEM_NAME),
        "inv_full": inventory_is_full(bot_e),
        "spots_visible": _last_spots_visible,
    }


def _runtime_status_payload(ctx: InfernalEelContext, runtime: RuntimeBridge, bot_e) -> None:
    p = ctx.progress
    runtime.merge_context(
        fsm_state=ctx.state.name,
        action_code=ctx.action_code,
        action_label=action_code_label(ctx.action_code),
        eel_count=ctx.eel_count,
        inv_slots=ctx.inv_slots,
        inv_full=ctx.inv_full,
        waiting_for_fish=ctx.waiting_for_fish,
        spots_visible=_last_spots_visible,
        last_spot_click=ctx.last_spot_click,
        cycles=ctx.cycles,
        progress_score=p.score,
        stagnation_streak=p.stagnation_streak,
        last_progress=p.last_event_label(),
    )
    runtime.publish_status(perception_status_from_eyes(bot_e))


def _print_startup_health(bot_e) -> None:
    global _last_spots_visible
    bind_inventory_to_eyes(bot_e, refresh_client=False)
    code = bot_e.get_action_text(refresh=False)
    hint = " — will seek spot" if code != 0 else ""
    print("Health: action line →", action_code_label(code) + hint)
    print("Health: eel item", EEL_ITEM_NAME, "| hammer item", HAMMER_ITEM_NAME)
    if bot_e.inventory_rect:
        print("Health: inventory_rect OK", bot_e.inventory_rect)
    else:
        print("Health: WARN inventory not found — slot count will be '?'")
    for stem in (EEL_ITEM_NAME, HAMMER_ITEM_NAME):
        path = Path("items") / ("%s.png" % stem)
        print("Health: item", stem, "OK" if path.is_file() else "MISSING (run label_inventory_item.py)")
    for template in SPOT_TEMPLATES:
        path = Path("images") / template
        print("Health: spot template", template, "OK" if path.is_file() else "MISSING")
    spot_hits = _locate_spots(bot_e)
    _last_spots_visible = len(spot_hits)
    print("Health: infernal spots visible now:", _last_spots_visible)


def _run_infernal_eel_session(args) -> None:
    """Question: How do I run the infernal eel fishing FSM session loop?

    Calls: ``bot_init``, ``InfernalEelMachine.step``, ``read_inventory_labels``, ``RuntimeBridge``.
    """
    win_rect, rect_source = _resolve_client_rect(args)
    if rect_source != "xdotool":
        print("Window mode:", rect_source)
        print("Capture:", os.environ.get("EXODIA_CAPTURE_BACKEND", "mss"))
        print("Input:", os.environ.get("EXODIA_INPUT_BACKEND", "pyautogui"))

    install_session_events("infernal_eel_fishing", path=EVENTS_LOG_FILE)
    log_event("session.start", rect_source=rect_source, max_cycles=args.max_cycles or 0)

    _register_stop_hotkey()
    ctx: Optional[InfernalEelContext] = None

    try:
        [client, bot_e, bot_a] = Actions.bot_init(
            win_rect=win_rect, window_title=args.window_title
        )
    except Client.RuneLiteNotFoundException as exc:
        print(str(exc), file=sys.stderr)
        print("Calibrate once: python calibrate_client_rect.py", file=sys.stderr)
        raise SystemExit(1)

    max_cycles = int(args.max_cycles)
    interval_s = args.interval
    timer_session_ms = int(os.environ.get("EXODIA_SESSION_MS", "6000000"))
    deadline = time.monotonic() + timer_session_ms / 1000.0
    next_cycle = time.monotonic()

    _print_startup_health(bot_e)

    overlay = None
    if args.overlay or os.environ.get("EXODIA_OVERLAY", "").strip().lower() in ("1", "true", "yes"):
        from bot_overlay import OverlayViewer, draw_bot_overlay

        overlay = OverlayViewer.from_env(LOGS_DIR)
        if overlay is not None:
            print("Overlay enabled — %s" % (overlay.save_path or "no save path"))

    ctx = InfernalEelContext(client=client, bot_e=bot_e, bot_a=bot_a)
    ctx.refresh(record_progress=False)
    if is_action_fishing(ctx.action_code):
        ctx.state = InfernalEelState.FISHING
    else:
        ctx.state = InfernalEelState.SEEK_SPOT
    machine = InfernalEelMachine(ctx)

    print(
        "Infernal eel FSM — states: FISHING | SEEK_SPOT | CRACKING (hammer→eel, %.2fs/tick)"
        % CRACK_TICK_DELAY_S
    )
    print("  Crack when inv full (%d slots) | poll interval %.0fs" % (INV_SLOT_COUNT, interval_s))
    print(
        "  After spot click: wait up to %.0fs for green fishing UI (poll %.1fs)"
        % (POST_CLICK_FISH_WAIT_S, POST_CLICK_FISH_POLL_S)
    )
    if max_cycles > 0:
        print("  Max FSM steps this run:", max_cycles)
    print("Images cwd:", os.getcwd())
    print("Initial state:", ctx.state.name)

    runtime_enabled = not args.no_runtime_control and _env_runtime_default()
    runtime = _build_runtime_bridge(ctx, machine, enabled=runtime_enabled)
    runtime.register_health_probe(lambda: _eel_health_probe(ctx))
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
        print("Runtime control disabled.")

    try:
        while time.monotonic() < deadline and not _stop.is_set():
            for line in runtime.poll():
                print("[runtime] %s" % line)
            _runtime_status_payload(ctx, runtime, bot_e)

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

            if overlay is not None:
                spot_pts = None
                if ctx.state.name == "SEEK_SPOT" and os.environ.get(
                    "EXODIA_OVERLAY_SPOTS", ""
                ).strip().lower() in ("1", "true", "yes"):
                    spot_pts = _locate_spots(bot_e)
                    _last_spots_visible = len(spot_pts or [])
                from bot_overlay import draw_bot_overlay

                frame = draw_bot_overlay(
                    bot_e,
                    state=ctx.state.name,
                    eel_count=ctx.eel_count,
                    inv_slots=ctx.inv_slots,
                    action_code=ctx.action_code,
                    spot_clicks=spot_pts,
                    last_click=ctx.last_spot_click,
                    last_action=runtime.last_action,
                )
                overlay.show(frame)

            if machine.should_throttle():
                p = ctx.progress
                stuck = " STUCK" if p.is_stagnant() else ""
                print(
                    "Cycle %d | %s | eels %d | inv %s | full %s | score %d | stagnation %d%s | last %s"
                    % (
                        ctx.cycles,
                        ctx.state.name,
                        ctx.eel_count,
                        ctx.inv_slots if ctx.inv_slots is not None else "?",
                        ctx.inv_full,
                        p.score,
                        p.stagnation_streak,
                        stuck,
                        p.last_event_label(),
                    )
                )
    except KeyboardInterrupt:
        print("\nCtrl+C — stopping.")
    finally:
        if overlay is not None:
            overlay.close()
        set_active_bridge(None)
        _unregister_stop_hotkey()
        if ctx is not None:
            print("Stopped after %d steps (final state: %s)." % (ctx.cycles, ctx.state.name))
            print("Progress:", ctx.progress.summary_line())
            close_session_events(
                {
                    "cycles": ctx.cycles,
                    "fsm_state": ctx.state.name,
                    "eel_count": ctx.eel_count,
                    "progress_score": ctx.progress.score,
                    "stagnation_streak": ctx.progress.stagnation_streak,
                    "stopped": _stop.is_set(),
                }
            )
        else:
            close_session_events({"stopped": True})


if __name__ == "__main__":
    _ensure_images_cwd()
    argv = sys.argv[1:]
    if argv and argv[0] == "diagnose":
        from . import infernal_eel_diagnose

        raise SystemExit(infernal_eel_diagnose.main())
    args = _parse_args(argv)

    if args.list_windows:
        _list_windows()
        raise SystemExit(0)

    if args.diagnose:
        from . import infernal_eel_diagnose

        raise SystemExit(infernal_eel_diagnose.main())

    if args.calibrate:
        import calibrate_client_rect

        raise SystemExit(calibrate_client_rect.main())

    install_run_logger(Path(args.log_file) if args.log_file else None)

    try:
        _run_infernal_eel_session(args)
    finally:
        close_run_logger()
