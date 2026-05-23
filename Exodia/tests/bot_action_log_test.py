"""Unit tests for bot_action_log."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("pyautogui", MagicMock())
sys.modules.setdefault("mouseinfo", MagicMock())

import json
import tempfile
import unittest
from pathlib import Path

from bot_action_log import ActionLogger, TickLogRecord, command_to_dict, make_run_id
from bot_harness import CmdClickImage, CmdLog


class ActionLogTest(unittest.TestCase):
    def test_command_to_dict(self):
        d = command_to_dict(CmdClickImage("fish.png"))
        self.assertEqual(d["type"], "CmdClickImage")
        self.assertEqual(d["template"], "fish.png")

    def test_log_tick_writes_jsonl_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = ActionLogger("test_run", root=Path(tmp))
            record = TickLogRecord(
                tick=1,
                skipped_agent=False,
                game_state={"action_busy": False, "action_line_text": "Idle"},
                commands=[command_to_dict(CmdClickImage("fish.png"))],
                logs=["Click fishing spot"],
            )
            logger.log_tick(record)
            logger.close(run_meta={"brain": "test"})

            jsonl = (Path(tmp) / "test_run" / "actions.jsonl").read_text(encoding="utf-8")
            line = json.loads(jsonl.strip())
            self.assertEqual(line["tick"], 1)
            self.assertEqual(line["commands"][0]["type"], "CmdClickImage")

            text = (Path(tmp) / "test_run" / "actions.log").read_text(encoding="utf-8")
            self.assertIn("CLICK fish.png", text)

            meta = json.loads((Path(tmp) / "test_run" / "run_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["brain"], "test")

    def test_make_run_id_format(self):
        rid = make_run_id()
        self.assertRegex(rid, r"^\d{8}T\d{6}Z$")


if __name__ == "__main__":
    unittest.main()
