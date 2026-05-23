"""Tests for inventory progress scoring."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest

from SacredEelFishing.sacred_eel_progress import InventoryProgressScore, STAGNATION_WARN_STREAK


class TestInventoryProgressScore(unittest.TestCase):
    def test_baseline_no_score(self):
        p = InventoryProgressScore()
        self.assertEqual(p.observe(5), "baseline")
        self.assertEqual(p.score, 0)

    def test_increase_scores_fishing(self):
        p = InventoryProgressScore()
        p.observe(10)
        self.assertEqual(p.observe(13), "fishing")
        self.assertEqual(p.score, 3)
        self.assertEqual(p.eels_gained, 3)
        self.assertEqual(p.stagnation_streak, 0)

    def test_decrease_scores_scaling(self):
        p = InventoryProgressScore()
        p.observe(20)
        self.assertEqual(p.observe(15), "scaling")
        self.assertEqual(p.score, 5)
        self.assertEqual(p.eels_processed, 5)

    def test_stagnation_does_not_increase_score(self):
        p = InventoryProgressScore()
        p.observe(8)
        p.observe(8)
        p.observe(8)
        self.assertEqual(p.score, 0)
        self.assertEqual(p.stagnation_streak, 2)
        self.assertTrue(p.is_stagnant() or STAGNATION_WARN_STREAK > 2)

    def test_progress_after_stagnation_resets_streak(self):
        p = InventoryProgressScore()
        p.observe(4)
        p.observe(4)
        self.assertEqual(p.stagnation_streak, 1)
        p.observe(6)
        self.assertEqual(p.stagnation_streak, 0)
        self.assertEqual(p.score, 2)

    def test_long_stagnation_does_not_imply_stop(self):
        p = InventoryProgressScore()
        p.observe(1)
        for _ in range(20):
            p.observe(1)
        self.assertEqual(p.stagnation_streak, 20)
        self.assertEqual(p.score, 0)


if __name__ == "__main__":
    unittest.main()
