"""
Session logging for sacred eel fishing — tee stdout/stderr to Exodia/logs/.

Canonical paths (for humans and agents reviewing runs):

  LOGS_DIR          — Exodia/logs/
  SESSION_LOG_FILE  — Exodia/logs/sacred_eel_latest.log  (truncated each run)
  EVENTS_LOG_FILE   — Exodia/logs/sacred_eel_fishing_events.jsonl (JSONL via bot_session_events)

Alias name (same script / ``EXODIA_EVENTS_LOG`` override; not a second file by default):

  sacred_eel_events.jsonl — historical label; default path is EVENTS_LOG_FILE above.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TextIO

EXODIA_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = EXODIA_DIR / "logs"
SESSION_LOG_FILE = LOGS_DIR / "sacred_eel_latest.log"
EVENTS_LOG_FILE = LOGS_DIR / "sacred_eel_fishing_events.jsonl"

_installed: Optional[Path] = None
_log_file: Optional[TextIO] = None
_orig_stdout: Optional[TextIO] = None
_orig_stderr: Optional[TextIO] = None


def ensure_logs_dir() -> Path:
    """Create ``Exodia/logs/`` if missing; return the directory path."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def default_log_path() -> Path:
    raw = __import__("os").environ.get("EXODIA_SACRED_EEL_LOG", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return SESSION_LOG_FILE


def log_path() -> Optional[Path]:
    """Active session log file, or ``None`` if logger not installed."""
    return _installed


def log_locations_banner(session_file: Optional[Path] = None) -> str:
    """Human-readable block printed at session start (also written to the log)."""
    path = (session_file or default_log_path()).resolve()
    ensure_logs_dir()
    return "\n".join(
        [
            "=== Exodia script logs ===",
            "Logs directory:  %s" % LOGS_DIR.resolve(),
            "This session:    %s" % path,
            "Tail live:       tail -f \"%s\"" % path,
            "(Agents: read SESSION_LOG_FILE in sacred_eel_log.py for the latest run.)",
            "",
        ]
    )


class _TeeStream:
    """Write to terminal and log file; flush both."""

    def __init__(self, terminal: TextIO, log: TextIO) -> None:
        self._terminal = terminal
        self._log = log

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._terminal.write(data)
        self._log.write(data)
        return len(data)

    def flush(self) -> None:
        self._terminal.flush()
        self._log.flush()

    def isatty(self) -> bool:
        return getattr(self._terminal, "isatty", lambda: False)()


def install_run_logger(path: Optional[Path] = None) -> Path:
    """
    Create ``logs/``, truncate the session file, tee stdout/stderr to it.

    Safe to call once per process; second call is a no-op.
    """
    global _installed, _log_file, _orig_stdout, _orig_stderr

    if _installed is not None:
        return _installed

    ensure_logs_dir()
    log_path_resolved = (path if path is not None else default_log_path()).resolve()
    if log_path_resolved.parent != LOGS_DIR.resolve() and path is None:
        # Custom env override — still ensure parent exists
        log_path_resolved.parent.mkdir(parents=True, exist_ok=True)

    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    _log_file = open(log_path_resolved, "w", encoding="utf-8", buffering=1)

    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _log_file.write(log_locations_banner(log_path_resolved))
    _log_file.write("=== sacred eel fishing session %s ===\n" % started)
    _log_file.flush()

    sys.stdout = _TeeStream(_orig_stdout, _log_file)
    sys.stderr = _TeeStream(_orig_stderr, _log_file)

    banner = log_locations_banner(log_path_resolved)
    _orig_stdout.write(banner)
    _orig_stdout.flush()

    _installed = log_path_resolved
    return log_path_resolved


def close_run_logger() -> None:
    """Restore stdio and close the log file."""
    global _installed, _log_file, _orig_stdout, _orig_stderr

    if _installed is None or _log_file is None:
        return

    ended = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    footer = "=== session end %s | log: %s ===\n" % (ended, _installed)
    if _orig_stdout is not None:
        _orig_stdout.write(footer)
    _log_file.write(footer)
    _log_file.flush()

    if _orig_stdout is not None:
        sys.stdout = _orig_stdout
    if _orig_stderr is not None:
        sys.stderr = _orig_stderr

    _log_file.close()
    _log_file = None
    _installed = None
    _orig_stdout = None
    _orig_stderr = None
