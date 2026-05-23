# Sacred eel fishing: fish at sacred eel spots, scale full stacks with a knife.
#
# Reference images (in ../images/ relative to Exodia):
#   osrs_sacredEelSpot.png, osrs_sacredEelSpot2.png — fishing spots in the playspace
#   osrs_sacredEelSpot_icon.png — eel sprite for spot verification (above cyan tile)
#   osrs_sacredEel.png — sacred eel icon in inventory
#   osrs_knife.png — knife for scaling eels into scales
#
# Run from Exodia (recommended):
#   cd Exodia && source exodia/bin/activate && python -m SacredEelFishing.sacred_eel_fishing
#   — or — ./SacredEelFishing/run_sacred_eel.sh
#
# Session log (all stdout/stderr):
#   Exodia/logs/sacred_eel_latest.log
#   tail -f Exodia/logs/sacred_eel_latest.log
# Paths: SacredEelFishing.sacred_eel_log.LOGS_DIR, SESSION_LOG_FILE
#
# Stop: press F8 (global hotkey) or Ctrl+C in the terminal.
#
# System packages (Linux/WSLg, once):
#   sudo apt-get install -y python3-tk python3-dev tesseract-ocr xdotool

import os
import random
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
        print("  cd Exodia", file=sys.stderr)
        print("  python3 -m venv exodia && source exodia/bin/activate", file=sys.stderr)
        print("  pip install -r requirements-minimal.txt", file=sys.stderr)
        print("  python -m SacredEelFishing.sacred_eel_fishing", file=sys.stderr)
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
import constants
from bot_gamestate import occupied_cell_count
import bot_eyes as Eyes
from bot_action_ui import action_code_label
from bot_perception_status import perception_status_from_eyes
from bot_runtime import (
    RuntimeBridge,
    RuntimeCommand,
    save_perception_snapshot,
    set_active_bridge,
)
from bot_session_events import close_session_events, install_session_events, log_event
from bot_inventory_count import count_sacred_eels
from bot_spot_verify import locate_sacred_eel_spots, sacred_eel_spot_click_points
from .sacred_eel_fsm import (
    SacredEelContext,
    SacredEelMachine,
    SacredEelState,
    _save_stagnation_snapshot,
    configure_fsm,
    is_action_fishing,
)
from .sacred_eel_log import (
    EVENTS_LOG_FILE,
    LOGS_DIR,
    SESSION_LOG_FILE,
    close_run_logger,
    install_run_logger,
)

STOP_HOTKEY = os.environ.get("EXODIA_STOP_HOTKEY", "f8")
_stop = threading.Event()

# Template filenames (resolved under cwd/images/ by bot_eyes)
SPOT_TEMPLATES = [
    "osrs_sacredEelSpot.png",
    "osrs_sacredEelSpot2.png",
]
EEL_INV = "osrs_sacredEel.png"
KNIFE_INV = "osrs_knife.png"
FULL_EEL_COUNT = 22
INV_SLOT_COUNT = Eyes.INV_SLOTS  # 4 x 7 = 28
INV_TEMPLATE_THRESHOLD = float(os.environ.get("EXODIA_INV_TEMPLATE_THRESHOLD", "0.35"))
SPOT_TEMPLATE_THRESHOLD = float(os.environ.get("EXODIA_SPOT_THRESHOLD", "0.45"))
MAX_SPOT_PAN_ATTEMPTS = int(os.environ.get("EXODIA_SPOT_PAN_ATTEMPTS", "8"))
MAX_SPOT_WALK_ATTEMPTS = int(os.environ.get("EXODIA_SPOT_WALK_ATTEMPTS", "4"))
# Wait after knife→eel before re-scanning inventory (1 OSRS tick ≈ 0.6s).
SCALE_TICK_DELAY_S = float(
    os.environ.get("EXODIA_SCALE_TICK_DELAY", str(constants.OSRS_TICK_S))
)
MAX_SCALE_ACTIONS = int(os.environ.get("EXODIA_MAX_SCALE_ACTIONS", "32"))
POST_CLICK_FISH_WAIT_S = float(os.environ.get("EXODIA_POST_CLICK_FISH_WAIT_S", "7"))
POST_CLICK_FISH_POLL_S = float(os.environ.get("EXODIA_POST_CLICK_FISH_POLL_S", "0.75"))

_last_spots_visible: int = 0


def _ensure_images_cwd() -> None:
    """Use Botting/ as cwd when images live beside Exodia/."""
    exodia_dir = Path(__file__).resolve().parent.parent
    botting_root = exodia_dir.parent
    images_dir = botting_root / "images"
    if images_dir.is_dir() and os.getcwd() != str(botting_root):
        os.chdir(botting_root)


def count_sacred_eels_in_inventory(bot_e) -> int:
    """Sacred eel stack count via ``bot_inventory_count`` (deduped template hits)."""
    return count_sacred_eels(bot_e, threshold=INV_TEMPLATE_THRESHOLD)


def inventory_occupied_slots(bot_e) -> Optional[int]:
    """Occupied inventory cells (0–28), or None if the grid could not be read."""
    pe = bot_e.perception_envelope or {}
    occ = pe.get("inventory_slot_occupancy")
    if occ is None:
        occ = bot_e.compute_inventory_slot_occupancy()
    return occupied_cell_count(occ)


def inventory_is_full(bot_e) -> bool:
    """True when all 28 inventory slots appear occupied."""
    n = inventory_occupied_slots(bot_e)
    return n is not None and n >= INV_SLOT_COUNT


def _locate_sacred_eels(bot_e) -> list:
    """
    Verified sacred eel spots in screen coordinates.

    Each hit is template-matched, then confirmed with the eel icon and cyan tile outline
    (see ``bot_spot_verify``). Click targets prefer the cyan marker centroid.
    """
    global _last_spots_visible

    def _on_reject(hit) -> None:
        log_event("perception.spot_reject", **hit.to_dict())

    candidates = locate_sacred_eel_spots(
        bot_e,
        SPOT_TEMPLATES,
        threshold=SPOT_TEMPLATE_THRESHOLD,
        on_reject=_on_reject,
    )
    points = sacred_eel_spot_click_points(candidates)
    _last_spots_visible = len(points)
    return points


def use_knife_on_eel(bot_e, bot_a) -> bool:
    """Click knife, then an eel (OSRS use-item order). Returns False if either is missing."""
    knives = bot_e.locate_image(
        filename=KNIFE_INV, inv=True, name="Knife", threshold=INV_TEMPLATE_THRESHOLD
    )
    eels = bot_e.locate_image(
        filename=EEL_INV, inv=True, name="Sacred eel", threshold=INV_TEMPLATE_THRESHOLD
    )
    if not knives or not eels:
        return False
    bot_a.click_at(knives[0], rad=11)
    _sleep_interruptible(random.uniform(0.12, 0.22))
    bot_a.click_at(random.choice(eels), rad=11)
    return True


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
    """Sleep in short slices so F8 / stop flag is honored during long waits."""
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
        _print_wsl_windows_runeLite_help()
        return
    print("Visible windows (id | title | geometry):")
    for wid, name in rows:
        geo = Wt.linux_window_geometry(wid)
        geo_s = "%s,%s,%s,%s" % geo if geo else "?, ?, ?, ?"
        print("  %6s | %s | %s" % (wid, name or "(no title)", geo_s))

    named = [r for r in rows if r[1] and "runelite" in r[1].lower()]
    if not named and len(rows) <= 2:
        print("")
        _print_wsl_windows_runeLite_help()


def _print_wsl_windows_runeLite_help() -> None:
    print("RuneLite is not visible to xdotool in this session.")
    print("")
    print("This usually means RuneLite is running on Windows, not as a WSLg/Linux app.")
    print("xdotool only sees Linux GUI windows — a single untitled full-screen entry")
    print("(e.g. 4920x1920) is the WSLg compositor, not your game client.")
    print("")
    print("Options:")
    print("  A) Run the bot from Windows Python (recommended for Windows RuneLite):")
    print("       cd Exodia")
    print("       python -m venv exodia")
    print("       exodia\\Scripts\\activate")
    print("       pip install -r requirements.txt")
    print("       python -m SacredEelFishing.sacred_eel_fishing")
    print("")
    print("  B) Run the Linux RuneLite .jar under WSLg so it appears in this list.")
    print("")
    print("  C) Calibrate window rect (WSL + Windows RuneLite):")
    print("       python calibrate_client_rect.py")
    print("       python -m SacredEelFishing.sacred_eel_fishing   # loads Exodia/client_rect.json")


def _env_runtime_default() -> bool:
    raw = (os.environ.get("EXODIA_RUNTIME", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _enable_wsl_ps_if_available() -> None:
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file():
        os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
        os.environ.setdefault("EXODIA_INPUT_BACKEND", "wsl_ps")


def _resolve_client_rect(args) -> tuple:
    """
    Return (win_rect or None, source_label).
    Priority: --rect > EXODIA_CLIENT_RECT > client_rect.json > auto xdotool.
    """
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
    p = argparse.ArgumentParser(description="Sacred eel fishing bot")
    p.add_argument(
        "--rect",
        metavar="L,T,W,H",
        help="Manual Win32 screen rect LEFT,TOP,WIDTH,HEIGHT (skips window search)",
    )
    p.add_argument(
        "--window-title",
        default=os.environ.get("EXODIA_WINDOW_TITLE", "RuneLite"),
        help="Window title substring for xdotool (default: RuneLite)",
    )
    p.add_argument(
        "--list-windows",
        action="store_true",
        help="Print visible X11 windows and exit (diagnostic)",
    )
    p.add_argument(
        "--calibrate",
        action="store_true",
        help="Run calibrate_client_rect.py to pick the RuneLite window, then exit",
    )
    p.add_argument(
        "--diagnose",
        action="store_true",
        help="One-shot perception check (inventory, spots, action strip); no clicks",
    )
    p.add_argument(
        "--log-file",
        metavar="PATH",
        default=os.environ.get("EXODIA_SACRED_EEL_LOG", "").strip(),
        help="Session log (default: %s)" % SESSION_LOG_FILE,
    )
    p.add_argument(
        "--max-cycles",
        type=int,
        default=int(os.environ.get("EXODIA_MAX_CYCLES", "30")),
        help="Stop after N FSM steps (0 = unlimited, default 30)",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("EXODIA_POLL_INTERVAL", "6")),
        help="Seconds between throttled polls (default 6)",
    )
    p.add_argument(
        "--no-runtime-control",
        action="store_true",
        help="Disable runtime_control.json / runtime_status.json polling",
    )
    p.add_argument(
        "--overlay",
        action="store_true",
        help="Live debug window + logs/diag/overlay_latest.png (or EXODIA_OVERLAY=1)",
    )
    return p.parse_args(argv)


def _build_runtime_bridge(
    ctx: SacredEelContext,
    machine: SacredEelMachine,
    *,
    enabled: bool,
) -> RuntimeBridge:
    bridge = RuntimeBridge(
        script_name="sacred_eel_fishing",
        enabled=enabled,
        poll_interval_s=float(os.environ.get("EXODIA_RUNTIME_POLL_S", "0.5")),
    )

    def _stop(_cmd: RuntimeCommand) -> str:
        _request_stop()
        return "stop requested"

    def _pause(_cmd: RuntimeCommand) -> str:
        bridge.paused = True
        return "paused — write resume to continue"

    def _resume(_cmd: RuntimeCommand) -> str:
        bridge.paused = False
        return "resumed"

    def _snapshot(_cmd: RuntimeCommand) -> str:
        tag = str(_cmd.args.get("tag") or "manual")
        out = save_perception_snapshot(ctx.bot_e, tag=tag)
        return "snapshot saved -> %s" % out

    def _refresh(_cmd: RuntimeCommand) -> str:
        Actions.bot_update(ctx.client, ctx.bot_e)
        ctx.action_code = ctx.bot_e.get_action_text_robust(refresh=False)
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
            raise ValueError("set_state requires args.state (FISHING, SEEK_SPOT, SCALING)")
        ctx.state = SacredEelState[name]
        return "state set to %s" % ctx.state.name

    def _stagnation_snapshot(_cmd: RuntimeCommand) -> str:
        _save_stagnation_snapshot(ctx)
        return "stagnation snapshot saved (see logs/diag/)"

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


def _eel_health_probe(ctx: SacredEelContext) -> dict:
    """Subset of ``sacred_eel_diagnose`` for runtime health probes."""
    bot_e = ctx.bot_e
    from bot_spot_verify import default_spot_verify_config

    cfg = default_spot_verify_config()
    templates = {
        name: (Path("images") / name).is_file()
        for name in SPOT_TEMPLATES + [EEL_INV, KNIFE_INV]
    }
    return {
        "templates": templates,
        "inventory_calibrated": bool(bot_e.inventory_rect),
        "action_code": int(bot_e.get_action_text_robust(refresh=False)),
        "eel_count": count_sacred_eels_in_inventory(bot_e),
        "spots_visible": _last_spots_visible,
        "spot_verify_enabled": cfg.enabled,
        "spot_threshold": SPOT_TEMPLATE_THRESHOLD,
    }


def _runtime_status_payload(ctx: SacredEelContext, runtime: RuntimeBridge, bot_e) -> None:
    p = ctx.progress
    runtime.merge_context(
        fsm_state=ctx.state.name,
        action_code=ctx.action_code,
        action_label=action_code_label(ctx.action_code),
        eel_count=ctx.eel_count,
        inv_slots=ctx.inv_slots,
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
    """Log perception prerequisites before the FSM loop."""
    bot_e.find_inventory(refresh_client=False)
    code = bot_e.get_action_text_robust(refresh=False)
    hint = " — will seek spot" if code != 0 else ""
    print("Health: action line →", action_code_label(code) + hint)
    print("Health: spot threshold", SPOT_TEMPLATE_THRESHOLD, "| inv template", INV_TEMPLATE_THRESHOLD)
    from bot_spot_verify import default_spot_verify_config

    svc = default_spot_verify_config()
    print(
        "Health: spot verify",
        "on" if svc.enabled else "off",
        "| eel icon",
        svc.eel_icon_file,
        "| cyan outline",
        "required" if svc.require_cyan_outline else "optional",
    )
    if bot_e.inventory_rect:
        print("Health: inventory_rect OK", bot_e.inventory_rect)
    else:
        print("Health: WARN inventory not found — slot count will be '?'")
    for template in SPOT_TEMPLATES + [EEL_INV, KNIFE_INV]:
        path = Path("images") / template
        print("Health: template", template, "OK" if path.is_file() else "MISSING")
    spot_hits = _locate_sacred_eels(bot_e)
    print("Health: sacred spots visible now:", len(spot_hits))


def _run_sacred_eel_session(args) -> None:
    win_rect, rect_source = _resolve_client_rect(args)
    if rect_source != "xdotool":
        print("Window mode:", rect_source)
        print("Capture:", os.environ.get("EXODIA_CAPTURE_BACKEND", "mss"))
        print("Input:", os.environ.get("EXODIA_INPUT_BACKEND", "pyautogui"))

    install_session_events("sacred_eel_fishing", path=EVENTS_LOG_FILE)
    log_event("session.start", rect_source=rect_source, max_cycles=args.max_cycles or 0)

    _register_stop_hotkey()
    ctx: Optional[SacredEelContext] = None

    try:
        [client, bot_e, bot_a] = Actions.bot_init(
            win_rect=win_rect, window_title=args.window_title
        )
    except Client.RuneLiteNotFoundException as exc:
        print(str(exc), file=sys.stderr)
        print("", file=sys.stderr)
        print("For Windows RuneLite from WSL, calibrate once:", file=sys.stderr)
        print("  python calibrate_client_rect.py", file=sys.stderr)
        print("  python -m SacredEelFishing.sacred_eel_fishing", file=sys.stderr)
        raise SystemExit(1)

    max_cycles = int(args.max_cycles)
    interval_s = args.interval
    timer_session_ms = int(os.environ.get("EXODIA_SESSION_MS", "6000000"))
    deadline = time.monotonic() + timer_session_ms / 1000.0
    next_cycle = time.monotonic()

    _print_startup_health(bot_e)

    overlay = None
    if args.overlay or os.environ.get("EXODIA_OVERLAY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        from bot_overlay import OverlayViewer, draw_bot_overlay
        from .sacred_eel_log import LOGS_DIR

        overlay = OverlayViewer.from_env(LOGS_DIR)
        if overlay is not None:
            print(
                "Overlay enabled — window + %s (set EXODIA_OVERLAY_WINDOW=0 to save PNG only)"
                % (overlay.save_path or "no save")
            )

    ctx = SacredEelContext(client=client, bot_e=bot_e, bot_a=bot_a)
    ctx.refresh(record_progress=False)
    if is_action_fishing(ctx.action_code):
        ctx.state = SacredEelState.FISHING
    else:
        ctx.state = SacredEelState.SEEK_SPOT
        if ctx.action_code == 2:
            print("Initial state: SEEK_SPOT (fishing action UI not visible)")
    machine = SacredEelMachine(ctx)

    print(
        "Sacred eel FSM — states: FISHING | SEEK_SPOT | SCALING (knife→eel, %.2fs/tick)"
        % SCALE_TICK_DELAY_S
    )
    print(
        "  Scale when inv full (%d slots) or >= %d eels | poll interval %.0fs"
        % (INV_SLOT_COUNT, FULL_EEL_COUNT, interval_s)
    )
    print(
        "  After spot click: wait up to %.0fs for green fishing UI (poll %.1fs)"
        % (POST_CLICK_FISH_WAIT_S, POST_CLICK_FISH_POLL_S)
    )
    print("  Progress score logged each FSM step (no stagnation auto-stop)")
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
        count_eels=count_sacred_eels_in_inventory,
        inv_slots=inventory_occupied_slots,
        inv_full=inventory_is_full,
        locate_spots=_locate_sacred_eels,
        use_knife_on_eel=use_knife_on_eel,
        spot_templates=SPOT_TEMPLATES,
        full_eel_count=FULL_EEL_COUNT,
        inv_slot_count=INV_SLOT_COUNT,
        max_spot_pan_attempts=MAX_SPOT_PAN_ATTEMPTS,
        max_spot_walk_attempts=MAX_SPOT_WALK_ATTEMPTS,
        scale_tick_delay_s=SCALE_TICK_DELAY_S,
        max_scale_actions=MAX_SCALE_ACTIONS,
        post_click_fish_wait_s=POST_CLICK_FISH_WAIT_S,
        post_click_fish_poll_s=POST_CLICK_FISH_POLL_S,
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
                if (
                    ctx.state.name == "SEEK_SPOT"
                    and os.environ.get("EXODIA_OVERLAY_SPOTS", "").strip().lower()
                    in ("1", "true", "yes")
                ):
                    spot_pts = _locate_sacred_eels(bot_e)
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
                    "Cycle %d | %s | eels %d | inv %s | score %d | stagnation %d%s | last %s"
                    % (
                        ctx.cycles,
                        ctx.state.name,
                        ctx.eel_count,
                        ctx.inv_slots if ctx.inv_slots is not None else "?",
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
        from . import sacred_eel_diagnose

        raise SystemExit(sacred_eel_diagnose.main())
    args = _parse_args(argv)

    if args.list_windows:
        _list_windows()
        raise SystemExit(0)

    if args.diagnose:
        from . import sacred_eel_diagnose

        raise SystemExit(sacred_eel_diagnose.main())

    if args.calibrate:
        import calibrate_client_rect
        raise SystemExit(calibrate_client_rect.main())

    install_run_logger(Path(args.log_file) if args.log_file else None)

    try:
        _run_sacred_eel_session(args)
    finally:
        close_run_logger()
