"""Unit tests for bot_harness (no live RuneLite)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

sys.modules.setdefault("pyautogui", MagicMock())
sys.modules.setdefault("mouseinfo", MagicMock())

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from bot_action_log import ActionLogger
from bot_gamestate import GameState
from bot_harness import (
    CallbackBrain,
    CmdLog,
    CmdWaitTicks,
    ExodiaHarness,
    IdleBrain,
    Observation,
)
from agents.reference_fishing_brain import ReferenceFishingBrain


class HarnessTest(unittest.TestCase):
    def _mock_harness(self, brain=None):
        client = MagicMock()
        client.win_rect = [0, 0, 800, 600]
        eyes = MagicMock()
        eyes.client_rect = [0, 0, 800, 600]
        eyes.perception_envelope = {"capture_backend": "mss", "inventory_slot_occupancy": None}
        eyes.get_action_text_with_ocr.return_value = (1, {"text": "Idle"})
        eyes.ocr_action_text_roi.return_value = {"text": "Idle"}
        eyes.ocr_dialogue_roi.return_value = {"text": ""}
        eyes.curr_client = np.zeros((600, 800, 3), dtype=np.uint8)
        eyes.curr_client_unmasked = eyes.curr_client
        eyes.locate_image.return_value = []
        arms = MagicMock()
        harness = ExodiaHarness(client, eyes, arms, brain=brain or IdleBrain())
        return harness, eyes, arms

    def test_callback_brain_cmds(self):
        def policy(obs, h):
            return [CmdLog("hello"), CmdWaitTicks(0)]

        harness, _, _ = self._mock_harness(CallbackBrain(policy))
        with patch("bot_harness.Actions.bot_update"):
            result = harness.step(refresh=False)
        self.assertFalse(result.skipped_agent)
        self.assertEqual(len(result.commands), 2)

    def test_action_logger_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = ActionLogger("h_test", root=Path(tmp))

            def policy(obs, h):
                return [CmdLog("tick action")]

            harness, _, _ = self._mock_harness(CallbackBrain(policy))
            harness.action_logger = logger
            with patch("bot_harness.Actions.bot_update"):
                harness.step(refresh=False)
            logger.close()
            text = (Path(tmp) / "h_test" / "actions.log").read_text(encoding="utf-8")
            self.assertIn("tick=1", text)

    def test_reference_brain_idle_clicks(self):
        brain = ReferenceFishingBrain()

        def policy_obs():
            gs = {
                "action_busy": False,
                "action_line_text": "Idle",
                "inventory_item_count": 0,
            }
            return Observation(
                tick=1,
                client_rect=[0, 0, 800, 600],
                action_text_code=1,
                action_line_text="Idle",
                meta={"game_state": gs},
            )

        harness, eyes, _ = self._mock_harness(brain)
        eyes.locate_image.return_value = []
        obs = policy_obs()
        with patch.object(Path, "is_file", return_value=True):
            cmds = brain.decide(obs, harness)
        types = [type(c).__name__ for c in cmds]
        self.assertIn("CmdClickImage", types)

    def test_reference_brain_cracking(self):
        brain = ReferenceFishingBrain()
        harness, eyes, _ = self._mock_harness(brain)
        eyes.locate_image.return_value = [[1, 2]] * 22
        gs = {"action_busy": True, "inventory_item_count": 22}
        obs = Observation(
            tick=2, client_rect=[], action_text_code=0,
            meta={"game_state": gs},
        )
        with patch.object(Path, "is_file", return_value=True):
            cmds = brain.decide(obs, harness)
        self.assertTrue(brain.cracking)
        self.assertTrue(any(type(c).__name__ == "CmdUseItemOn" for c in cmds))


if __name__ == "__main__":
    unittest.main()
