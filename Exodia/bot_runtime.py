"""
Live control and status for long-running Exodia scripts.

While a bot runs, write commands to a JSON control file; the main loop polls it
and updates a status file each tick. Use :func:`exodia_ctl_main` or ``exodia_ctl.py``
from another terminal without restarting the session.

Default paths (under ``Exodia/logs/``):

- ``runtime_control.json`` — pending command (overwritten per request)
- ``runtime_status.json``  — latest bot snapshot (rewritten each poll)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from SacredEelFishing.sacred_eel_log import LOGS_DIR, ensure_logs_dir

__all__ = [
    "RuntimeBridge",
    "RuntimeCommand",
    "default_control_path",
    "default_status_path",
    "exodia_ctl_main",
    "get_active_bridge",
    "parse_control_command",
    "register_module_health_probe",
    "run_health_probes",
    "save_perception_snapshot",
    "set_active_bridge",
    "write_json_atomic",
]

_active_bridge: Optional["RuntimeBridge"] = None
_health_probe_registry: Dict[str, List[Callable[[], Any]]] = {}

_log_runtime_command: Optional[Callable[..., None]] = None


def _get_log_event() -> Optional[Callable[..., None]]:
    global _log_runtime_command
    if _log_runtime_command is not None:
        return _log_runtime_command
    try:
        from bot_session_events import log_event as fn
    except ImportError:
        return None
    _log_runtime_command = fn
    return fn

Handler = Callable[["RuntimeCommand"], Optional[str]]


@dataclass(frozen=True)
class RuntimeCommand:
    """One control-file instruction."""

    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    issued_at: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


def default_control_path() -> Path:
    raw = os.environ.get("EXODIA_RUNTIME_CONTROL", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (LOGS_DIR / "runtime_control.json").resolve()


def set_active_bridge(bridge: Optional["RuntimeBridge"]) -> None:
    """Track the live bridge for this process (optional; control file is canonical)."""
    global _active_bridge
    _active_bridge = bridge


def get_active_bridge() -> Optional["RuntimeBridge"]:
    return _active_bridge


def register_module_health_probe(script_name: str, probe: Callable[[], Any]) -> None:
    """Register a health probe by script id (used when no live bridge is active)."""
    key = script_name.strip()
    _health_probe_registry.setdefault(key, []).append(probe)


def run_health_probes(probes: List[Callable[[], Any]]) -> List[Any]:
    results: List[Any] = []
    for probe in probes:
        try:
            results.append(probe())
        except Exception as exc:
            results.append({"error": str(exc)})
    return results


def default_status_path() -> Path:
    raw = os.environ.get("EXODIA_RUNTIME_STATUS", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (LOGS_DIR / "runtime_status.json").resolve()


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON via temp file + rename (readers never see half a file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_control_command(data: Dict[str, Any]) -> RuntimeCommand:
    name = str(data.get("command") or data.get("cmd") or "").strip().lower()
    if not name:
        raise ValueError("control file missing 'command'")
    args = data.get("args")
    if args is None:
        args = {k: v for k, v in data.items() if k not in ("command", "cmd", "issued_at")}
    if not isinstance(args, dict):
        args = {}
    issued = data.get("issued_at")
    return RuntimeCommand(name=name, args=args, issued_at=issued, raw=data)


def _read_control_file(path: Path) -> Optional[RuntimeCommand]:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return parse_control_command(data)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


class RuntimeBridge:
    """
    Poll ``control_path`` and dispatch commands; publish ``status_path`` each tick.

    Handlers return an optional ack message printed to the session log.
    """

    def __init__(
        self,
        *,
        script_name: str,
        control_path: Optional[Path] = None,
        status_path: Optional[Path] = None,
        enabled: bool = True,
        poll_interval_s: float = 0.5,
    ) -> None:
        ensure_logs_dir()
        self.script_name = script_name
        self.control_path = control_path or default_control_path()
        self.status_path = status_path or default_status_path()
        self.enabled = enabled
        self.poll_interval_s = max(0.1, float(poll_interval_s))
        self._last_poll = 0.0
        self._handlers: Dict[str, Handler] = {}
        self._health_probes: List[Callable[[], Any]] = []
        self.paused = False
        self.force_step = False
        self.messages: List[str] = []
        self.last_action: Optional[str] = None
        self.stop_reason: Optional[str] = None
        self.session_started_at = datetime.now(timezone.utc).isoformat()
        self.context: Dict[str, Any] = {}

    def register(self, command: str, handler: Handler) -> None:
        self._handlers[command.strip().lower()] = handler

    def register_health_probe(self, probe: Callable[[], Any]) -> None:
        """Register a callable invoked by the ``health`` runtime command."""
        self._health_probes.append(probe)
        register_module_health_probe(self.script_name, probe)

    def run_health(self) -> List[Any]:
        """Run registered probes and stash results on ``context['health']``."""
        results = run_health_probes(self._health_probes)
        self.merge_context(health=results[0] if len(results) == 1 else results)
        return results

    def set_last_action(self, msg: Optional[str]) -> None:
        self.last_action = msg

    def merge_context(self, **kwargs: Any) -> None:
        self.context.update(kwargs)

    def _session_uptime_s(self) -> float:
        if not self.session_started_at:
            return 0.0
        started = datetime.fromisoformat(self.session_started_at.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())

    def control_help(self) -> str:
        cmds = sorted(self._handlers.keys())
        return (
            "Runtime control file: %s\n"
            "Live status file:     %s\n"
            "Send commands:        python Exodia/exodia_ctl.py <cmd>\n"
            "  or: echo '{\"command\":\"pause\"}' > \"%s\"\n"
            "Commands: %s"
            % (self.control_path, self.status_path, self.control_path, ", ".join(cmds))
        )

    def poll(self) -> List[str]:
        """Poll control file (rate-limited). Returns ack lines to print."""
        if not self.enabled:
            return []
        now = time.monotonic()
        if now - self._last_poll < self.poll_interval_s:
            return []
        self._last_poll = now
        cmd = _read_control_file(self.control_path)
        if cmd is None:
            return []
        try:
            self.control_path.unlink(missing_ok=True)
        except OSError:
            pass
        handler = self._handlers.get(cmd.name)
        if handler is None:
            msg = "Unknown runtime command: %s" % cmd.name
            self.messages.append(msg)
            log_event = _get_log_event()
            if log_event is not None:
                log_event("runtime.command", command=cmd.name, ack=msg)
            return [msg]
        try:
            ack = handler(cmd)
            msg = ack or ("OK: %s" % cmd.name)
        except Exception as exc:
            msg = "Command %s failed: %s" % (cmd.name, exc)
        self.messages.append(msg)
        log_event = _get_log_event()
        if log_event is not None:
            log_event("runtime.command", command=cmd.name, ack=msg)
        return [msg]

    def publish_status(self, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        perception = payload.get("perception")
        script_fields = {
            k: v
            for k, v in payload.items()
            if k not in ("perception", "context")
        }
        body: Dict[str, Any] = {
            "script": self.script_name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "paused": self.paused,
            "control_file": str(self.control_path),
            "status_file": str(self.status_path),
            "last_action": self.last_action,
            "stop_reason": self.stop_reason,
            "session_started_at": self.session_started_at,
            "session_uptime_s": round(self._session_uptime_s(), 3),
            "context": dict(self.context),
            **script_fields,
        }
        if perception is not None:
            body["perception"] = perception
        write_json_atomic(self.status_path, body)

    def wait_while_paused(self, stop_check: Callable[[], bool], sleep_fn: Callable[[float], None]) -> None:
        while self.paused and not stop_check():
            for line in self.poll():
                print("[runtime] %s" % line)
            sleep_fn(0.2)


def save_perception_snapshot(
    bot_e: Any,
    *,
    tag: str = "manual",
    log_dir: Optional[Path] = None,
) -> Path:
    """Save client / inventory / action-strip PNGs under ``logs/diag/<tag>``."""
    import cv2

    ensure_logs_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (log_dir or LOGS_DIR / "diag") / ("%s_%s" % (tag, stamp))
    out.mkdir(parents=True, exist_ok=True)
    if bot_e.curr_client is not None and bot_e.curr_client.size > 0:
        cv2.imwrite(str(out / "client.png"), bot_e.curr_client)
    if bot_e.curr_inventory is not None and bot_e.curr_inventory.size > 0:
        cv2.imwrite(str(out / "inventory.png"), bot_e.curr_inventory)
    strip_fn = getattr(bot_e, "_action_strip_bgr", None)
    if callable(strip_fn):
        strip = strip_fn()
        if strip is not None and strip.size > 0:
            cv2.imwrite(str(out / "action_strip.png"), strip)
    return out


def _read_status_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _print_health_snapshot(status: Dict[str, Any]) -> None:
    script = status.get("script") or "(unknown)"
    print("\n--- health snapshot (%s) ---" % script)
    print("updated_at:", status.get("updated_at"))
    print("paused:", status.get("paused"))
    print("stop_reason:", status.get("stop_reason"))
    ctx = status.get("context")
    if isinstance(ctx, dict) and ctx:
        print("context:")
        for key in sorted(ctx.keys()):
            print("  %s: %s" % (key, ctx[key]))
    perception = status.get("perception")
    if isinstance(perception, dict) and perception:
        print("perception:")
        for key in sorted(perception.keys()):
            print("  %s: %s" % (key, perception[key]))
    health = status.get("health")
    if health is None and isinstance(ctx, dict):
        health = ctx.get("health")
    if health is not None:
        print("health:", json.dumps(health, indent=2, default=str))


def _offline_health_probes(script_name: str) -> List[Any]:
    probes = list(_health_probe_registry.get(script_name, []))
    if probes:
        return run_health_probes(probes)
    return []


def exodia_ctl_main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python exodia_ctl.py pause|resume|stop|status|snapshot|...``"""
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Send a command to a running Exodia script")
    p.add_argument(
        "command",
        nargs="?",
        default="status",
        help="Command name (default: status — prints paths and last status JSON)",
    )
    p.add_argument("--args", default="", help="JSON object of extra args")
    p.add_argument("--control-file", default="", help="Override control file path")
    args = p.parse_args(argv)

    control = Path(args.control_file).expanduser().resolve() if args.control_file else default_control_path()
    status = default_status_path()

    if args.command == "status":
        print("Control file:", control)
        print("Status file: ", status)
        data = _read_status_json(status)
        if data is not None:
            print(json.dumps(data, indent=2, default=str))
        else:
            print("(no status file yet — bot may not be running)")
        return 0

    if args.command == "health":
        payload = {
            "command": "health",
            "args": {},
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(control, payload)
        print("Queued command 'health' -> %s" % control)

        data = _read_status_json(status)
        bridge = get_active_bridge()
        if bridge is not None and bridge.enabled:
            print("(live bridge in this process — bot loop will run probes on poll)")
        elif data is not None:
            _print_health_snapshot(data)
            script = str(data.get("script") or "")
            offline = _offline_health_probes(script) if script else []
            if offline:
                print("\nmodule health probes:")
                print(json.dumps(offline, indent=2, default=str))
        else:
            print("(no status file — bot may not be running)")
        return 0

    extra: Dict[str, Any] = {}
    if args.args.strip():
        extra = json.loads(args.args)

    payload = {
        "command": args.command,
        "args": extra,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(control, payload)
    print("Queued command %r -> %s" % (args.command, control))
    return 0


if __name__ == "__main__":
    raise SystemExit(exodia_ctl_main())
