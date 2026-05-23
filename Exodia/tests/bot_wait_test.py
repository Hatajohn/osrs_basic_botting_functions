"""Tests for generic polling."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest

from bot_wait import poll_until


class TestPollUntil(unittest.TestCase):
    def test_succeeds_before_timeout(self):
        n = [0]

        def pred():
            n[0] += 1
            return n[0] if n[0] >= 3 else None

        r = poll_until(pred, timeout_s=1.0, interval_s=0.0, sleep_fn=lambda _s: None)
        self.assertTrue(r.success)
        self.assertEqual(r.value, 3)
        self.assertEqual(r.polls, 3)

    def test_succeeds_when_value_is_zero(self):
        r = poll_until(lambda: 0, timeout_s=1.0, interval_s=0.0, sleep_fn=lambda _s: None)
        self.assertTrue(r.success)
        self.assertEqual(r.value, 0)

    def test_cancelled(self):
        r = poll_until(
            lambda: None,
            timeout_s=1.0,
            interval_s=0.0,
            sleep_fn=lambda _s: None,
            stop_check=lambda: True,
        )
        self.assertFalse(r.success)
        self.assertTrue(r.cancelled)


if __name__ == "__main__":
    unittest.main()
