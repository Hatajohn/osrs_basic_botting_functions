"""Tests for sacred eel spot verification helpers."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import os
import unittest
from typing import List

import cv2
import numpy as np

from bot_spot_verify import (
    SpotVerifyConfig,
    SacredEelSpotCandidate,
    cyan_marker_ratio,
    dedupe_spot_candidates,
    eel_icon_score_at,
    filter_sacred_eel_spots,
    template_trust_fallback,
    verify_spot_at_client_xy,
)


class TestBotSpotVerify(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(str(Path(__file__).resolve().parents[2]))

    def tearDown(self):
        os.chdir(self._cwd)

    def test_cyan_marker_detects_teal_patch(self):
        patch = np.zeros((40, 40, 3), dtype=np.uint8)
        patch[20:35, 10:30] = (255, 255, 0)  # BGR yellow-cyan
        ratio, centroid = cyan_marker_ratio(patch)
        self.assertGreater(ratio, 0.05)
        self.assertIsNotNone(centroid)

    def test_eel_icon_scores_on_reference_crop(self):
        user = (
            "/home/hata/.cursor/projects/home-hata-Botting-Exodia/assets/"
            "c__Users_hataj_AppData_Roaming_Cursor_User_workspaceStorage_"
            "fe222b6d4b7f46a8ace5083cc3531354_images_"
            "image-d0ee4046-8198-4e62-8d8a-fa5002cd20b3.png"
        )
        if not os.path.isfile(user):
            self.skipTest("reference spot image not available")
        bgr = cv2.imread(user)
        cfg = SpotVerifyConfig(require_cyan_outline=True, require_eel_icon=True)
        cx, cy = bgr.shape[1] // 2, int(bgr.shape[0] * 0.55)
        ok, eel_s, cyan_r, _click = verify_spot_at_client_xy(bgr, (cx, cy), cfg)
        self.assertTrue(ok, "eel=%.2f cyan=%.3f" % (eel_s, cyan_r))
        self.assertGreaterEqual(eel_s, cfg.eel_threshold)
        self.assertGreaterEqual(cyan_r, cfg.cyan_min_ratio)

    def test_dedupe_keeps_best_score(self):
        a = SacredEelSpotCandidate(
            screen_xy=[10, 10],
            client_xy=[10, 10],
            spot_score=0.9,
            eel_score=0.5,
            cyan_ratio=0.1,
            template="a",
            verified=True,
            click_xy=[10, 10],
        )
        b = SacredEelSpotCandidate(
            screen_xy=[12, 11],
            client_xy=[12, 11],
            spot_score=0.5,
            eel_score=0.5,
            cyan_ratio=0.1,
            template="b",
            verified=True,
            click_xy=[12, 11],
        )
        out = dedupe_spot_candidates([b, a], radius_px=20)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].spot_score, 0.9)

    def _candidate(self, *, verified: bool, spot_score: float = 0.8, template: str = "t") -> SacredEelSpotCandidate:
        return SacredEelSpotCandidate(
            screen_xy=[100, 100],
            client_xy=[100, 100],
            spot_score=spot_score,
            eel_score=0.5,
            cyan_ratio=0.1,
            template=template,
            verified=verified,
            click_xy=[100, 100],
        )

    def test_filter_on_reject_called_for_failures(self):
        good = self._candidate(verified=True, template="good")
        bad = self._candidate(verified=False, template="bad")
        rejected: List[SacredEelSpotCandidate] = []

        def _on_reject(c: SacredEelSpotCandidate) -> None:
            rejected.append(c)

        out = filter_sacred_eel_spots(
            [good, bad],
            SpotVerifyConfig(enabled=True),
            on_reject=_on_reject,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].template, "good")
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].template, "bad")

    def test_filter_return_rejects_tuple(self):
        good = self._candidate(verified=True, template="good")
        bad1 = self._candidate(verified=False, template="bad1")
        bad2 = self._candidate(verified=False, template="bad2")
        verified, rejected = filter_sacred_eel_spots(
            [good, bad1, bad2],
            SpotVerifyConfig(enabled=True),
            return_rejects=True,
        )
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].template, "good")
        self.assertEqual({c.template for c in rejected}, {"bad1", "bad2"})

    def test_template_trust_fallback_accepts_strong_match(self):
        weak = self._candidate(verified=False, spot_score=0.55, template="spot")
        out = template_trust_fallback([weak], [], trust_threshold=0.50, dedupe_radius_px=28)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].verified)
        self.assertEqual(out[0].spot_score, 0.55)

    def test_template_trust_fallback_skips_low_score(self):
        weak = self._candidate(verified=False, spot_score=0.40, template="spot")
        out = template_trust_fallback([weak], [], trust_threshold=0.50, dedupe_radius_px=28)
        self.assertEqual(len(out), 0)

    def test_filter_skips_reject_tracking_when_disabled(self):
        bad = self._candidate(verified=False, template="bad")
        rejected: List[SacredEelSpotCandidate] = []
        out = filter_sacred_eel_spots(
            [bad],
            SpotVerifyConfig(enabled=False),
            on_reject=rejected.append,
            return_rejects=True,
        )
        verified, failed = out
        self.assertEqual(len(verified), 1)
        self.assertEqual(len(failed), 0)
        self.assertEqual(len(rejected), 0)


if __name__ == "__main__":
    unittest.main()
