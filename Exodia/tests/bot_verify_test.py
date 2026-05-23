"""Unit tests for bot_verify."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest

from bot_gamestate import GameState
from bot_verify import verify_action


class VerifyTest(unittest.TestCase):
    def _state(self, **kwargs) -> GameState:
        defaults = dict(
            tick=1,
            action_busy=False,
            action_line_text="Idle",
            dialogue_text=None,
            inventory_occupied=None,
            inventory_item_count=0,
            inventory_calibrated=True,
            client_rect=[0, 0, 800, 600],
            capture_backend="mss",
        )
        defaults.update(kwargs)
        return GameState(**defaults)

    def test_action_line_changed(self):
        before = self._state(action_line_text="Idle")
        after = self._state(action_line_text="Fishing...")
        result = verify_action(before, after)
        self.assertTrue(result.changed)
        self.assertTrue(result.signals.get("action_line_changed"))

    def test_inventory_count_delta(self):
        before = self._state(inventory_item_count=10)
        after = self._state(inventory_item_count=11)
        result = verify_action(before, after)
        self.assertTrue(result.changed)
        self.assertEqual(result.signals.get("inventory_count_delta"), 1)

    def test_no_change(self):
        s = self._state()
        result = verify_action(s, s)
        self.assertFalse(result.changed)


if __name__ == "__main__":
    unittest.main()
