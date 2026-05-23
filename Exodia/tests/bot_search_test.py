"""Tests for playspace search helpers."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest
from unittest.mock import MagicMock

from bot_search import (
    click_random_hit,
    ground_click_target,
    playspace_search_roi,
    search_with_camera_pan,
    walk_direction_for_attempt,
)


class TestBotSearch(unittest.TestCase):
    def test_playspace_roi(self):
        roi = playspace_search_roi(800, 600)
        self.assertEqual(roi, [0, 0, 560, 420])

    def test_search_with_pan_finds_on_second_attempt(self):
        pans = []
        calls = [0]

        def locate():
            calls[0] += 1
            return [[10, 10]] if calls[0] >= 2 else []

        hits = search_with_camera_pan(
            locate,
            lambda: pans.append(1),
            max_pan_attempts=3,
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(hits, [[10, 10]])
        self.assertEqual(len(pans), 1)

    def test_click_random_hit(self):
        clicked = []
        click_random_hit(lambda p: clicked.append(p), [[1, 2], [3, 4]])
        self.assertEqual(len(clicked), 1)

    def test_walk_direction_cycles(self):
        self.assertEqual(walk_direction_for_attempt(0), "north")
        self.assertEqual(walk_direction_for_attempt(1), "east")
        self.assertEqual(walk_direction_for_attempt(4), "north")

    def test_ground_click_north_of_center(self):
        client = [100, 50, 800, 600]
        center = [500, 350]
        pt = ground_click_target(client, center, "north", distance_frac=0.32, y_jitter_frac=0.0)
        self.assertLess(pt[1], center[1])
        self.assertGreaterEqual(pt[0], client[0] + 40)

    def test_search_relocate_after_pans(self):
        walks = []
        locate_calls = [0]

        def locate():
            locate_calls[0] += 1
            return [[20, 20]] if locate_calls[0] >= 3 else []

        hits = search_with_camera_pan(
            locate,
            lambda: None,
            max_pan_attempts=1,
            sleep_fn=lambda _s: None,
            relocate=lambda i, m: walks.append((i, m)),
            max_relocate_attempts=2,
            sleep_after_relocate_s=0.0,
        )
        self.assertEqual(hits, [[20, 20]])
        self.assertEqual(walks, [(1, 2)])


if __name__ == "__main__":
    unittest.main()
