"""Tests for generic session event JSONL logging."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot_session_events as events


class SessionEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        events._reset_for_tests()
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("EXODIA_EVENTS", None)
        os.environ.pop("EXODIA_EVENTS_LOG", None)

    def tearDown(self) -> None:
        events._reset_for_tests()
        self._env_patch.stop()

    def test_install_writes_jsonl_and_truncates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a_events.jsonl"
            path.write_text('{"old": true}\n', encoding="utf-8")

            events.install_session_events("script_a", path=path)
            events.log_event("fsm.transition", step=1, state="IDLE")

            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["script"], "script_a")
            self.assertEqual(row["event"], "fsm.transition")
            self.assertEqual(row["step"], 1)
            self.assertEqual(row["state"], "IDLE")
            self.assertIn("ts", row)

    def test_two_script_ids_use_distinct_default_paths(self):
        with patch.object(events, "LOGS_DIR", Path(tempfile.mkdtemp())):
            events._reset_for_tests()
            p_a = events.default_events_path("alpha")
            p_b = events.default_events_path("beta")
            self.assertNotEqual(p_a, p_b)
            self.assertEqual(p_a.name, "alpha_events.jsonl")
            self.assertEqual(p_b.name, "beta_events.jsonl")

    def test_log_event_noop_when_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.jsonl"
            events.log_event("ignored", x=1)
            self.assertFalse(path.exists())

    def test_current_script_id(self):
        self.assertIsNone(events.current_script_id())
        events.install_session_events("eel", path=Path(tempfile.mkdtemp()) / "e.jsonl")
        self.assertEqual(events.current_script_id(), "eel")
        events.close_session_events()
        self.assertIsNone(events.current_script_id())

    def test_close_session_end_merges_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "end.jsonl"
            events.install_session_events("script_b", path=path)
            events.close_session_events(meta={"cycles": 42, "reason": "done"})

            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["event"], "session.end")
            self.assertEqual(row["cycles"], 42)
            self.assertEqual(row["reason"], "done")

    def test_exodia_events_zero_disables_writes(self):
        os.environ["EXODIA_EVENTS"] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "disabled.jsonl"
            sess = events.install_session_events("off", path=path)
            self.assertFalse(sess.enabled)
            events.log_event("should.not.write")
            self.assertFalse(path.exists())
            self.assertEqual(events.current_script_id(), "off")

    def test_exodia_events_log_overrides_default_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "custom.jsonl"
            os.environ["EXODIA_EVENTS_LOG"] = str(override)
            events.install_session_events("ignored_id")
            events.log_event("ping")
            self.assertTrue(override.is_file())
            row = json.loads(override.read_text(encoding="utf-8").strip())
            self.assertEqual(row["event"], "ping")

    def test_second_install_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "first.jsonl"
            path_b = Path(tmp) / "second.jsonl"
            events.install_session_events("first", path=path_a)
            events.install_session_events("second", path=path_b)
            events.log_event("only.first")
            self.assertTrue(path_a.is_file())
            self.assertFalse(path_b.exists())
            self.assertEqual(events.current_script_id(), "first")


if __name__ == "__main__":
    unittest.main()
