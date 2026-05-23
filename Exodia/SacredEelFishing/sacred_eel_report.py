#!/usr/bin/env python3
"""Sacred eel session report — defaults for eel events + FSM/perception highlights."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .sacred_eel_log import EVENTS_LOG_FILE

from session_report import DEFAULT_SCRIPT, load_events, print_report, summarize_events

EEL_PREFIX_LINES = (
    ("fsm.scaling", "fsm.scaling"),
    ("perception.spot", "perception.spot_*"),
    ("progress.stagnation", "progress.stagnation_*"),
)


def print_eel_highlights(summary: Dict[str, Any]) -> None:
    counts = summary.get("event_counts") or {}
    print("\nSacred eel highlights:")
    for label, prefix in EEL_PREFIX_LINES:
        if prefix.endswith("*"):
            p = prefix[:-1]
            total = sum(n for name, n in counts.items() if name.startswith(p))
        else:
            total = counts.get(prefix, 0)
        print("  %6d  %s" % (total, label))


def run(argv: Optional[List[str]] = None) -> int:
    """Run generic report with eel defaults, then print prefix highlights."""
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["--script", DEFAULT_SCRIPT, "--events", str(EVENTS_LOG_FILE)]
    elif "--events" not in argv and "-h" not in argv and "--help" not in argv:
        argv = ["--script", DEFAULT_SCRIPT, "--events", str(EVENTS_LOG_FILE)] + list(argv)

    events_path = Path(EVENTS_LOG_FILE)
    for i, tok in enumerate(argv):
        if tok == "--events" and i + 1 < len(argv):
            events_path = Path(argv[i + 1]).expanduser().resolve()
            break

    try:
        rows = load_events(events_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    summary = summarize_events(rows, script=DEFAULT_SCRIPT)
    print_report(summary, events_path=events_path)
    print_eel_highlights(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
