"""Tests for session_report JSONL summarization."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
import tempfile
import unittest
from pathlib import Path

from session_report import load_events, summarize_events


class SessionReportTest(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list) -> None:
        path.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )

    def test_summarize_counts_and_session_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sacred_eel_fishing_events.jsonl"
            self._write_jsonl(
                path,
                [
                    {"ts": "2026-01-02T10:00:00+00:00", "script": "sacred_eel_fishing", "event": "session.start"},
                    {"ts": "2026-01-02T10:01:00+00:00", "script": "sacred_eel_fishing", "event": "fsm.scaling", "phase": "start"},
                    {"ts": "2026-01-02T10:02:00+00:00", "script": "sacred_eel_fishing", "event": "progress.stagnation_stop", "streak": 8},
                    {"ts": "2026-01-02T10:03:00+00:00", "script": "sacred_eel_fishing", "event": "session.end", "reason": "done"},
                ],
            )
            rows = load_events(path)
            summary = summarize_events(rows, script="sacred_eel_fishing")
            self.assertEqual(summary["event_count"], 4)
            self.assertEqual(summary["event_counts"]["fsm.scaling"], 1)
            self.assertEqual(summary["time_range"][0], "2026-01-02T10:00:00+00:00")
            self.assertEqual(summary["time_range"][1], "2026-01-02T10:03:00+00:00")
            self.assertIsNotNone(summary["session_start"])
            self.assertIsNotNone(summary["session_end"])
            self.assertEqual(summary["stop_reason"], "done")

    def test_stop_reason_from_stagnation_event(self):
        rows = [
            {"ts": "t1", "script": "sacred_eel_fishing", "event": "progress.stagnation_stop", "streak": 5},
        ]
        summary = summarize_events(rows, script="sacred_eel_fishing")
        self.assertIn("stagnation", summary["stop_reason"])


if __name__ == "__main__":
    unittest.main()
