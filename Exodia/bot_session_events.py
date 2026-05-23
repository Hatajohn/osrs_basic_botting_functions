"""
Generic append-only JSONL session events for any Exodia script.

Each line: ``{"ts", "script", "event", ...fields}``. Install once per process;
``log_event`` is a no-op when not installed or when ``EXODIA_EVENTS=0``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TextIO

__all__ = [
    "SessionEvents",
    "close_session_events",
    "current_script_id",
    "default_events_path",
    "events_enabled",
    "install_session_events",
    "log_event",
]

EXODIA_DIR = Path(__file__).resolve().parent
LOGS_DIR = EXODIA_DIR / "logs"

_installed: Optional["SessionEvents"] = None


def events_enabled() -> bool:
    raw = (os.environ.get("EXODIA_EVENTS") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def default_events_path(script_id: str) -> Path:
    raw = os.environ.get("EXODIA_EVENTS_LOG", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (LOGS_DIR / ("%s_events.jsonl" % script_id)).resolve()


class SessionEvents:
    """One installed session event sink (file may be absent when disabled)."""

    def __init__(
        self,
        script_id: str,
        path: Optional[Path],
        fp: Optional[TextIO],
        *,
        enabled: bool,
    ) -> None:
        self.script_id = script_id
        self.path = path
        self._fp = fp
        self.enabled = enabled
        self.started_at = datetime.now(timezone.utc).isoformat()

    def log(self, event: str, **fields: Any) -> None:
        if not self.enabled or self._fp is None:
            return
        payload: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "script": self.script_id,
            "event": event,
        }
        payload.update(fields)
        self._fp.write(json.dumps(payload, default=str) + "\n")
        self._fp.flush()


def install_session_events(script_id: str, *, path: Optional[Path] = None) -> SessionEvents:
    """
    Open (truncate) the events JSONL for ``script_id``.

    Second call in one process returns the existing installation.
    When ``EXODIA_EVENTS=0``, returns a disabled handle and writes nothing.
    """
    global _installed

    if _installed is not None:
        return _installed

    if not events_enabled():
        sess = SessionEvents(script_id=script_id, path=None, fp=None, enabled=False)
        _installed = sess
        return sess

    if path is not None:
        events_path = Path(path).expanduser().resolve()
    else:
        events_path = default_events_path(script_id)

    events_path.parent.mkdir(parents=True, exist_ok=True)
    fp = open(events_path, "w", encoding="utf-8")
    sess = SessionEvents(script_id=script_id, path=events_path, fp=fp, enabled=True)
    _installed = sess
    return sess


def close_session_events(meta: Optional[Dict[str, Any]] = None) -> None:
    """Emit ``session.end``, close the file, and clear the installation."""
    global _installed

    if _installed is None:
        return

    fields = dict(meta or {})
    if _installed.enabled and _installed._fp is not None:
        _installed.log("session.end", **fields)
        _installed._fp.close()

    _installed = None


def log_event(event: str, **fields: Any) -> None:
    """Append one event; no-op if session events are not installed or disabled."""
    if _installed is None:
        return
    _installed.log(event, **fields)


def current_script_id() -> Optional[str]:
    if _installed is None:
        return None
    return _installed.script_id


def _reset_for_tests() -> None:
    """Clear module state (unit tests only)."""
    global _installed

    if _installed is not None and _installed._fp is not None:
        _installed._fp.close()
    _installed = None
