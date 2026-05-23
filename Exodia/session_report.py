"""
Summarize a script's JSONL session events (``bot_session_events`` format).

Default events path: ``logs/<script>_events.jsonl`` under :data:`bot_session_events.LOGS_DIR`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot_session_events import LOGS_DIR, default_events_path

__all__ = [
    "default_report_events_path",
    "load_events",
    "summarize_events",
    "main",
    "print_report",
]

DEFAULT_SCRIPT = "sacred_eel_fishing"


def default_report_events_path(script: str) -> Path:
    return default_events_path(script)


def load_events(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError("events file not found: %s" % path)
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def summarize_events(
    rows: Iterable[Dict[str, Any]],
    *,
    script: Optional[str] = None,
) -> Dict[str, Any]:
    """Build summary dict from JSONL rows."""
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        if script and row.get("script") != script:
            continue
        filtered.append(row)

    counts: Counter[str] = Counter()
    timestamps: List[str] = []
    session_start: Optional[Dict[str, Any]] = None
    session_end: Optional[Dict[str, Any]] = None
    stop_reason: Optional[str] = None

    for row in filtered:
        event = str(row.get("event") or "")
        if event:
            counts[event] += 1
        ts = row.get("ts")
        if isinstance(ts, str) and ts:
            timestamps.append(ts)
        if event == "session.start":
            session_start = row
        if event == "session.end":
            session_end = row

    for row in reversed(filtered):
        if row.get("stop_reason"):
            stop_reason = str(row["stop_reason"])
            break
        if row.get("reason") and str(row.get("event", "")).startswith(("session.", "progress.", "runtime.")):
            stop_reason = str(row["reason"])
            break
        if row.get("event") == "progress.stagnation_stop":
            streak = row.get("streak")
            stop_reason = "stagnation (streak=%s)" % streak if streak is not None else "stagnation"
            break

    time_range: Optional[Tuple[str, str]] = None
    if timestamps:
        time_range = (min(timestamps), max(timestamps))

    return {
        "script": script,
        "event_count": len(filtered),
        "event_counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "time_range": time_range,
        "session_start": session_start,
        "session_end": session_end,
        "stop_reason": stop_reason,
        "logs_dir": str(LOGS_DIR.resolve()),
    }


def print_report(summary: Dict[str, Any], *, events_path: Path) -> None:
    print("Events file: %s" % events_path.resolve())
    print("Logs dir:    %s" % summary.get("logs_dir"))
    if summary.get("script"):
        print("Script filter: %s" % summary["script"])
    print("Total events: %d" % summary["event_count"])
    tr = summary.get("time_range")
    if tr:
        print("Time range: %s .. %s" % tr)
    else:
        print("Time range: (no timestamps)")

    start = summary.get("session_start")
    if start:
        print("session.start: ts=%s fields=%s" % (start.get("ts"), _extra_fields(start)))
    else:
        print("session.start: (not found)")

    end = summary.get("session_end")
    if end:
        print("session.end:   ts=%s fields=%s" % (end.get("ts"), _extra_fields(end)))
    else:
        print("session.end:   (not found)")

    stop = summary.get("stop_reason")
    print("stop_reason:   %s" % (stop if stop else "(not in events)"))

    print("\nEvent counts:")
    for name, n in summary.get("event_counts", {}).items():
        print("  %6d  %s" % (n, name))


def _extra_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    skip = {"ts", "script", "event"}
    return {k: v for k, v in row.items() if k not in skip}


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize Exodia session event JSONL")
    p.add_argument(
        "--script",
        default=DEFAULT_SCRIPT,
        help="Script id filter and default events filename (default: %s)" % DEFAULT_SCRIPT,
    )
    p.add_argument(
        "--events",
        default="",
        help="Path to events JSONL (default: logs/<script>_events.jsonl)",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    events_path = (
        Path(args.events).expanduser().resolve()
        if args.events.strip()
        else default_report_events_path(args.script)
    )
    try:
        rows = load_events(events_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print("Invalid JSONL in %s: %s" % (events_path, exc), file=sys.stderr)
        return 1

    summary = summarize_events(rows, script=args.script)
    print_report(summary, events_path=events_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
