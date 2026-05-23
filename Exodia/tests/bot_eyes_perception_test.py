"""Tests for perception / template helpers (no RuneLite required)."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest

import numpy as np
import cv2

import bot_eyes as eyes_mod


class TestActionStripRoi(unittest.TestCase):
    def test_left_of_inventory(self):
        inv = [140, 306, 182, 255]
        roi = eyes_mod.resolve_action_strip_roi_client(
            inventory_rect=inv, frame_w=1919, frame_h=1033
        )
        self.assertLessEqual(roi[0] + roi[2], inv[0] - 1)
        self.assertGreaterEqual(roi[1] + roi[3], inv[1] + inv[3] - 40)

    def test_manual_rect_env_override(self):
        import os

        os.environ["EXODIA_ACTION_STRIP_RECT"] = "10,20,30,40"
        try:
            roi = eyes_mod.resolve_action_strip_roi_client(inventory_rect=[500, 500, 100, 100])
            self.assertEqual(roi, [10, 20, 30, 40])
        finally:
            os.environ.pop("EXODIA_ACTION_STRIP_RECT", None)


class TestMatchTemplatePeaks(unittest.TestCase):
    def test_finds_single_peak(self):
        bg = np.zeros((100, 100), dtype=np.uint8)
        bg[:, :] = 20
        tpl = np.zeros((10, 10), dtype=np.uint8)
        tpl[:, :] = 200
        tpl[2:8, 3:8] = 100
        x0, y0 = 55, 35
        bg[y0 : y0 + 10, x0 : x0 + 10] = tpl
        res = cv2.matchTemplate(bg, tpl, cv2.TM_CCOEFF_NORMED)
        peaks = eyes_mod._match_template_peaks(res, 10, 10, threshold=0.98, max_peaks=8)
        self.assertGreaterEqual(len(peaks), 1)
        peaks.sort(key=lambda t: (-t[2], t[0], t[1]))
        self.assertEqual(peaks[0][0], x0)
        self.assertEqual(peaks[0][1], y0)


class TestPerceptionEnvelope(unittest.TestCase):
    def test_envelope_after_update_shape_only(self):
        e = eyes_mod.BotEyes(win_rect=[0, 0, 200, 200], DEBUG=False)
        e.curr_client = np.zeros((200, 200, 3), dtype=np.uint8)
        e.curr_inventory = np.zeros((50, 50, 3), dtype=np.uint8)
        e.local_center = [100, 100]
        e.global_center = [100, 100]
        e.inventory_rect = [10, 10, 50, 50]
        e.inventory_global = [10, 10, 50, 50]
        e.chat_rect = [0, 170, 100, 30]
        e._rebuild_perception_envelope()
        self.assertIsNotNone(e.perception_envelope)
        self.assertEqual(e.perception_envelope["curr_client_shape_hw"], [200, 200])
        self.assertIn("mask_regions_applied_to_curr_client", e.perception_envelope)


class TestGameState(unittest.TestCase):
    def test_build_game_state_from_mock_eyes(self):
        from bot_gamestate import build_game_state, occupied_cell_count

        e = eyes_mod.BotEyes(win_rect=[0, 0, 200, 200], DEBUG=False)
        e.curr_client = np.zeros((200, 200, 3), dtype=np.uint8)
        e.client_rect = [0, 0, 200, 200]
        e._rebuild_perception_envelope()
        e.get_action_text_with_ocr = lambda refresh=False: (1, {"text": "Idle"})  # type: ignore
        e.ocr_dialogue_roi = lambda: {"text": ""}  # type: ignore

        gs = build_game_state(e, tick=1)
        self.assertEqual(gs.tick, 1)
        self.assertFalse(gs.action_busy)
        self.assertEqual(gs.action_line_text, "Idle")
        self.assertEqual(occupied_cell_count([[True, False], [False, False]]), 1)


class TestWriteTickFrames(unittest.TestCase):
    def test_write_tick_frames_keys(self):
        import tempfile
        from pathlib import Path
        from bot_frames import write_tick_frames

        e = eyes_mod.BotEyes(win_rect=[0, 0, 100, 100], DEBUG=False)
        e.curr_client = np.zeros((100, 100, 3), dtype=np.uint8)
        e.curr_client_unmasked = e.curr_client
        e.client_rect = [0, 0, 100, 100]
        e.chat_rect = [0, 70, 50, 20]
        e._rebuild_perception_envelope()

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_tick_frames(e, Path(tmp), "t", ocr=False)
            self.assertIn("world_masked", paths)


if __name__ == "__main__":
    unittest.main()
