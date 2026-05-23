"""Unit tests for bot_track motion blob pipeline (synthetic frames, no screen)."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest

import cv2
import numpy as np

from bot_track import (
    TrackConfig,
    TrackState,
    detect_blobs,
    motion_mask,
    scaled_min_area,
    track_blobs_from_frame,
    update_tracks,
)


def _blank(h: int, w: int) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _square_frame(h: int, w: int, x: int, y: int, size: int = 20) -> np.ndarray:
    img = _blank(h, w)
    cv2.rectangle(img, (x, y), (x + size, y + size), (255, 255, 255), -1)
    return img


class MotionMaskTests(unittest.TestCase):
    def test_moving_square_produces_blob(self):
        h, w = 100, 100
        prev = _square_frame(h, w, 10, 10)
        curr = _square_frame(h, w, 30, 10)
        cfg = TrackConfig(min_area=50, diff_threshold=20, blur_size=5)
        mask = motion_mask(prev, curr, config=cfg)
        blobs = detect_blobs(mask, min_area=50)
        self.assertGreaterEqual(len(blobs), 1)
        cx, cy = blobs[0]["centroid"]
        self.assertGreater(cx, 15)

    def test_static_frames_empty_blobs(self):
        h, w = 100, 100
        frame = _square_frame(h, w, 10, 10)
        cfg = TrackConfig(min_area=50)
        mask = motion_mask(frame, frame.copy(), config=cfg)
        blobs = detect_blobs(mask, min_area=50)
        self.assertEqual(len(blobs), 0)

    def test_static_exclude_zeros_region(self):
        h, w = 100, 100
        prev = _blank(h, w)
        curr = _blank(h, w)
        cv2.rectangle(curr, (60, 0), (100, 40), (255, 255, 255), -1)
        exclude = [[60, 0, 40, 40]]
        cfg = TrackConfig(min_area=30, diff_threshold=15, blur_size=5)
        mask = motion_mask(prev, curr, static_exclude=exclude, config=cfg)
        blobs = detect_blobs(mask, min_area=30)
        self.assertEqual(len(blobs), 0)


class TrackPipelineTests(unittest.TestCase):
    def test_track_blobs_from_frame_sequence(self):
        h, w = 120, 160
        state = TrackState()
        cfg = TrackConfig(min_area=40, max_distance=80, max_disappeared=3)
        f0 = _square_frame(h, w, 20, 20)
        f1 = _square_frame(h, w, 40, 20)
        track_blobs_from_frame(f0, state, config=cfg)
        tracks, _ = track_blobs_from_frame(f1, state, config=cfg)
        self.assertGreaterEqual(len(tracks), 1)

    def test_update_tracks_max_distance_rejects_far_match(self):
        state = TrackState()
        cfg = TrackConfig(max_distance=10, max_disappeared=2)
        d0 = [{"bbox": [10, 10, 10, 10], "centroid": (15, 15), "area": 100.0}]
        update_tracks(state, d0, config=cfg)
        d1 = [{"bbox": [80, 80, 10, 10], "centroid": (85, 85), "area": 100.0}]
        tracks = update_tracks(state, d1, config=cfg)
        ids = {t.track_id for t in tracks}
        self.assertEqual(len(ids), 2)


class ScalingTests(unittest.TestCase):
    def test_scaled_min_area_grows_with_playspace(self):
        small = scaled_min_area(320, 240)
        large = scaled_min_area(640, 480)
        self.assertGreater(large, small)


if __name__ == "__main__":
    unittest.main()
