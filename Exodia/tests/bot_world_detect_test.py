#!/usr/bin/env python3
"""
World object **eyes** tests — template match in the playspace (no mouse input).

Offline (default) — uses ``tests/fixtures/inventory/reference.png`` (structural run;
expect zero infernal eel hits unless you add a world fixture)::

  python tests/bot_world_detect_test.py
  python -m unittest tests.bot_world_detect_test -v

Live — RuneLite capture::

  python tests/bot_world_detect_test.py --live

Override offline frame::

  EXODIA_WORLD_OFFLINE_IMAGE=captures/live_probe_now.png python tests/bot_world_detect_test.py

Writes ``captures/world_detect_overlay.png`` (gitignored) with cyan ROI, hit markers,
and green status lines (font size 20) at the top-left of the capture.
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import os
import unittest
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

import bot_actions as Actions
from bot_client_config import load_client_rect
from bot_world_objects import (
    capture_template_path,
    draw_world_detect_overlay,
    locate_world_objects,
    locate_world_objects_from_eyes,
    world_match_threshold,
    world_template_names,
)
from tests.inventory_test_common import (
    capture_client_bgr,
    draw_test_results_on_image,
    exodia_dir,
    load_offline_client,
    locate_inventory_rect,
)

_EXODIA_DIR = exodia_dir()
_OVERLAY_OUT = _EXODIA_DIR / "captures" / "world_detect_overlay.png"


def world_live_mode() -> bool:
    return os.environ.get("EXODIA_WORLD_TEST_LIVE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def load_offline_world_client() -> tuple[Optional[np.ndarray], Optional[str]]:
    raw = os.environ.get("EXODIA_WORLD_OFFLINE_IMAGE", "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (_EXODIA_DIR / path).resolve()
        if not path.is_file():
            return None, "offline image missing: %s" % path
        client = cv2.imread(str(path))
        if client is None or client.size == 0:
            return None, "could not read %s" % path
        return client, None

    client, _meta, err = load_offline_client()
    if client is not None:
        return client, None
    return None, err or "offline reference missing"


class TestWorldDetectEyes(unittest.TestCase):
    """Locate world templates in the playspace — capture/vision only."""

    client: Optional[np.ndarray] = None
    inv_rect: Optional[List[int]] = None
    chat_rect: Optional[List[int]] = None
    hits: List[Any] = []
    cyan_regions: List[Any] = []
    cyan_rejected: int = 0
    search_roi: Optional[List[int]] = None
    inventory_filtered: int = 0
    result_lines: List[str] = []
    live: bool = False
    template_names: List[str] = []
    threshold: float = 0.45

    @classmethod
    def _record(cls, line: str) -> None:
        cls.result_lines.append(line)

    @classmethod
    def setUpClass(cls) -> None:
        os.chdir(_EXODIA_DIR)
        cls.result_lines = []
        cls.live = world_live_mode()
        cls.template_names = world_template_names()
        cls.threshold = world_match_threshold()
        cls._record("suite: world detect eyes")
        cls._record("mode: %s" % ("live" if cls.live else "offline"))
        cls._record("templates: %s" % ",".join(cls.template_names))
        cls._record("threshold: %.3f" % cls.threshold)

        missing = [n for n in cls.template_names if not capture_template_path(n).is_file()]
        if missing:
            raise unittest.SkipTest("missing capture templates: %s" % ", ".join(missing))

        if cls.live:
            client, err = capture_client_bgr()
            if client is None:
                raise unittest.SkipTest(err or "could not capture client frame")
        else:
            client, err = load_offline_world_client()
            if client is None:
                raise unittest.SkipTest(err or "offline client missing")

        cls.client = client
        cls.inv_rect = None
        cls.chat_rect = None
        cls.hits = []
        cls.cyan_regions = []
        cls.cyan_rejected = 0
        cls.search_roi = None
        cls.inventory_filtered = 0

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.client is None:
            return

        overlay = draw_world_detect_overlay(
            cls.client,
            cls.hits,
            inventory_rect=cls.inv_rect,
            search_roi=cls.search_roi,
            cyan_regions=cls.cyan_regions,
        )
        overlay = draw_test_results_on_image(overlay, cls.result_lines)
        _OVERLAY_OUT.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_OVERLAY_OUT), overlay)

        print("\nworld detect overlay: %s" % _OVERLAY_OUT)
        for line in cls.result_lines:
            print("  %s" % line)

    def test_locate_world_objects(self) -> None:
        assert TestWorldDetectEyes.client is not None
        client = TestWorldDetectEyes.client

        if TestWorldDetectEyes.live:
            rect = load_client_rect()
            if not rect or len(rect) != 4:
                TestWorldDetectEyes._record("bot init: FAIL missing client_rect.json")
                self.fail("missing client_rect.json")
            _client, bot_e, _bot_a = Actions.bot_init(win_rect=rect)
            Actions.bot_update(_client, bot_e)
            client = bot_e.curr_client
            if client is None or client.size == 0:
                TestWorldDetectEyes._record("capture: FAIL blank frame")
                self.fail("blank client capture")
            TestWorldDetectEyes.client = client
            inv = bot_e.inventory_rect
            TestWorldDetectEyes.inv_rect = list(inv) if inv else None
            TestWorldDetectEyes.chat_rect = (
                list(bot_e.chat_rect) if bot_e.chat_rect else None
            )
            result = locate_world_objects_from_eyes(bot_e, TestWorldDetectEyes.template_names)
        else:
            inv_rect, _score, _grid = locate_inventory_rect(client)
            TestWorldDetectEyes.inv_rect = list(inv_rect) if inv_rect else None
            h0, w0 = client.shape[:2]
            TestWorldDetectEyes.chat_rect = [0, h0 - 30, 520, 30]
            result = locate_world_objects(
                client,
                TestWorldDetectEyes.template_names,
                inventory_rect=TestWorldDetectEyes.inv_rect,
                chat_rect=TestWorldDetectEyes.chat_rect,
            )

        TestWorldDetectEyes.hits = result.hits
        TestWorldDetectEyes.search_roi = result.search_roi
        TestWorldDetectEyes.inventory_filtered = result.inventory_filtered
        TestWorldDetectEyes.cyan_regions = result.cyan_regions
        TestWorldDetectEyes.cyan_rejected = result.cyan_rejected

        TestWorldDetectEyes._record(
            "detect: cyan-first (markers=%d rejected=%d)"
            % (len(result.cyan_regions), result.cyan_rejected)
        )

        if TestWorldDetectEyes.inv_rect is not None:
            TestWorldDetectEyes._record(
                "inventory_rect: PASS %s" % TestWorldDetectEyes.inv_rect
            )
        else:
            TestWorldDetectEyes._record("inventory_rect: WARN not located")

        if result.search_roi is not None:
            TestWorldDetectEyes._record("search_roi: %s" % result.search_roi)
        else:
            TestWorldDetectEyes._record("search_roi: FAIL could not compute ROI")
            self.fail("playspace_search_roi returned None")

        TestWorldDetectEyes._record(
            "inventory filter drops: %d" % result.inventory_filtered
        )
        TestWorldDetectEyes._record("hits: %d" % len(result.hits))
        for hit in result.hits:
            TestWorldDetectEyes._record(
                "hit %s client=(%d,%d) score=%.3f"
                % (hit.name, hit.client_xy[0], hit.client_xy[1], hit.score)
            )

        if TestWorldDetectEyes.live:
            min_hits = int(os.environ.get("EXODIA_WORLD_MIN_HITS", "1"))
            if min_hits > 0:
                ok = len(result.hits) >= min_hits
                TestWorldDetectEyes._record(
                    "live hit count: %s want>=%d got=%d"
                    % ("PASS" if ok else "FAIL", min_hits, len(result.hits))
                )
                self.assertGreaterEqual(len(result.hits), min_hits)
        else:
            TestWorldDetectEyes._record(
                "offline: structural run (set EXODIA_WORLD_OFFLINE_IMAGE for eel frame)"
            )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="World object eyes tests (vision/detection only).")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Capture live client (OSRS visible) instead of offline PNG",
    )
    args, _rest = parser.parse_known_args(argv)

    os.chdir(_EXODIA_DIR)
    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    os.environ["EXODIA_WORLD_TEST_LIVE"] = "1" if args.live else "0"

    suite = unittest.TestSuite([TestWorldDetectEyes("test_locate_world_objects")])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
