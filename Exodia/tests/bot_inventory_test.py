#!/usr/bin/env python3
"""
Inventory **eyes** tests — vision/detection only (no mouse input).

Offline (default) — uses ``tests/fixtures/inventory/reference.{png,json}``::

  python tests/bot_inventory_test.py
  python -m unittest tests.bot_inventory_test -v

Online — live capture, still eyes-only (no drags)::

  python tests/bot_inventory_test.py --online

Arms tests (drag items) are separate::

  python tests/bot_inventory_arms_test.py --online

Refresh offline fixture from a live capture (files stay local — not committed)::

  python tests/bot_inventory_test.py --online --refresh-fixture

Writes ``captures/inventory_test_overlay.png`` (gitignored) with grid overlay and
green PASS/FAIL lines (font size 20) at the top-left of the capture.

Offline runs also write ``captures/offline_inventory_detect.png`` — same style with
item labels on occupied slots (known name or ``?``).
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

import bot_inventory_detect as inv_detect
from bot_inventory_detect import (
    draw_inventory_occupancy_overlay,
    inventory_occupancy_from_client,
    inventory_outline_template_path,
)
from bot_inventory_items import (
    draw_inventory_item_identify_overlay,
    identify_inventory_slot_items,
    items_directory,
    load_item_templates,
)
from tests.inventory_test_common import (
    capture_client_bgr,
    draw_test_results_on_image,
    exodia_dir,
    load_offline_client,
    locate_inventory_rect,
    online_mode,
    save_fixture,
)

_EXODIA_DIR = exodia_dir()
_OVERLAY_OUT = _EXODIA_DIR / "captures" / "inventory_test_overlay.png"
_OFFLINE_DETECT_OUT = _EXODIA_DIR / "captures" / "offline_inventory_detect.png"


class TestInventoryEyes(unittest.TestCase):
    """Find inventory, count slots, identify items — capture/vision only."""

    client: Optional[np.ndarray] = None
    meta: Optional[Dict[str, Any]] = None
    inv_rect: Optional[List[int]] = None
    outline_score: float = 0.0
    grid_score: float = 0.0
    occ: Optional[List[List[bool]]] = None
    item_count: int = 0
    result_lines: List[str] = []
    online: bool = False
    slot_items: Optional[List[List[Optional[str]]]] = None

    @classmethod
    def _record(cls, line: str) -> None:
        cls.result_lines.append(line)

    @classmethod
    def setUpClass(cls) -> None:
        os.chdir(_EXODIA_DIR)
        os.environ["EXODIA_INV_CALIB_USE_EEL"] = "0"
        inv_detect._outline_cache = None
        cls.result_lines = []
        cls.slot_items = None
        cls.online = online_mode()
        cls._record("suite: eyes")
        cls._record("mode: %s" % ("online" if cls.online else "offline"))

        if not inventory_outline_template_path().is_file():
            raise unittest.SkipTest("missing inventory outline template")

        if cls.online:
            client, err = capture_client_bgr()
            if client is None:
                raise unittest.SkipTest(err or "could not capture client frame")
            cls.meta = None
        else:
            client, meta, err = load_offline_client()
            if client is None:
                raise unittest.SkipTest(err or "offline reference missing")
            cls.meta = meta

        cls.client = client
        cls.inv_rect = None
        cls.occ = None

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.client is None:
            return

        if cls.inv_rect is not None and cls.slot_items is not None:
            overlay = draw_inventory_item_identify_overlay(
                cls.client,
                cls.inv_rect,
                cls.slot_items,
                cls.occ,
            )
        elif cls.inv_rect is not None and cls.occ is not None:
            overlay = draw_inventory_occupancy_overlay(cls.client, cls.inv_rect, cls.occ)
        elif cls.inv_rect is not None:
            overlay = draw_inventory_occupancy_overlay(cls.client, cls.inv_rect)
        else:
            overlay = cls.client.copy()

        overlay = draw_test_results_on_image(overlay, cls.result_lines)
        _OVERLAY_OUT.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_OVERLAY_OUT), overlay)

        print("\ninventory eyes overlay: %s" % _OVERLAY_OUT)
        if not cls.online and cls.inv_rect is not None and cls.slot_items is not None:
            detect_vis = draw_inventory_item_identify_overlay(
                cls.client,
                cls.inv_rect,
                cls.slot_items,
                cls.occ,
            )
            detect_vis = draw_test_results_on_image(detect_vis, cls.result_lines)
            cv2.imwrite(str(_OFFLINE_DETECT_OUT), detect_vis)
            print("offline detect: %s" % _OFFLINE_DETECT_OUT)
        for line in cls.result_lines:
            print("  %s" % line)

    def test_find_inventory(self) -> None:
        assert TestInventoryEyes.client is not None
        if TestInventoryEyes.online:
            client, err = capture_client_bgr()
            if client is None:
                TestInventoryEyes._record("find inventory: FAIL %s" % (err or "capture"))
                self.fail(err or "could not capture client frame")
            TestInventoryEyes.client = client
        else:
            client = TestInventoryEyes.client

        inv_rect, score, grid_score = locate_inventory_rect(client)
        if inv_rect is None:
            TestInventoryEyes._record("find inventory: FAIL auto-detect")
            self.fail("inventory auto-detect failed")

        TestInventoryEyes.inv_rect = list(inv_rect)
        TestInventoryEyes.outline_score = float(score)
        TestInventoryEyes.grid_score = float(grid_score)

        min_score = float(os.environ.get("EXODIA_INV_OUTLINE_MIN_SCORE", "0.55"))
        outline_ok = score >= min_score
        TestInventoryEyes._record(
            "find inventory: %s rect=%s score=%.3f"
            % ("PASS" if outline_ok else "FAIL", inv_rect, score)
        )
        self.assertGreaterEqual(score, min_score)

        min_grid = float(os.environ.get("EXODIA_INV_MIN_GRID_SCORE", "12"))
        grid_ok = grid_score >= min_grid
        TestInventoryEyes._record(
            "grid validation: %s score=%.1f" % ("PASS" if grid_ok else "FAIL", grid_score)
        )
        self.assertGreaterEqual(grid_score, min_grid)

        fx, fy, fw, fh = inv_rect
        h0, w0 = client.shape[:2]
        in_bounds = fx > 0 and fy > 0 and fx + fw < w0 + 4 and fy + fh < h0 + 4
        TestInventoryEyes._record(
            "inventory in frame: %s" % ("PASS" if in_bounds else "FAIL")
        )
        self.assertGreater(fx, 0)
        self.assertGreater(fy, 0)
        self.assertLess(fx + fw, w0 + 4)
        self.assertLess(fy + fh, h0 + 4)

        if not TestInventoryEyes.online and TestInventoryEyes.meta is not None:
            expected = TestInventoryEyes.meta["inventory_rect_client_local"]
            tol = int(os.environ.get("EXODIA_INV_REF_TOL_PX", "8"))
            rect_ok = all(abs(inv_rect[i] - expected[i]) <= tol for i in range(4))
            TestInventoryEyes._record(
                "rect vs reference: %s tol=%dpx" % ("PASS" if rect_ok else "FAIL", tol)
            )
            for i in range(4):
                self.assertLessEqual(abs(inv_rect[i] - expected[i]), tol)

    def test_count_items(self) -> None:
        assert TestInventoryEyes.client is not None
        if TestInventoryEyes.inv_rect is None:
            TestInventoryEyes._record("count items: FAIL (inventory not located — run find first)")
            self.fail("inventory not located")

        client = TestInventoryEyes.client
        inv_rect = TestInventoryEyes.inv_rect

        occ, count, proto = inventory_occupancy_from_client(client, inv_rect)
        if occ is None:
            TestInventoryEyes._record("count items: FAIL occupancy grid")
            self.fail("occupancy detection failed")

        TestInventoryEyes.occ = occ
        TestInventoryEyes.item_count = int(count)

        count_ok = 0 <= count <= 28
        filled = [[r, c] for r in range(7) for c in range(4) if occ[r][c]]
        TestInventoryEyes._record(
            "count items: %s %d / 28 occupied %s"
            % ("PASS" if count_ok else "FAIL", count, filled)
        )
        self.assertGreaterEqual(count, 0)
        self.assertLessEqual(count, 28)

        if TestInventoryEyes.online:
            raw_expect = os.environ.get("EXODIA_INV_EXPECT_COUNT", "").strip()
            if raw_expect:
                expect = int(raw_expect)
                expect_ok = count == expect
                TestInventoryEyes._record(
                    "expected count: %s want=%d got=%d"
                    % ("PASS" if expect_ok else "FAIL", expect, count)
                )
                self.assertEqual(count, expect)
        elif TestInventoryEyes.meta is not None:
            expect = int(TestInventoryEyes.meta["occupied_count"])
            expect_ok = count == expect
            TestInventoryEyes._record(
                "count vs reference: %s want=%d got=%d"
                % ("PASS" if expect_ok else "FAIL", expect, count)
            )
            self.assertEqual(count, expect)

        if (
            TestInventoryEyes.online
            and os.environ.get("EXODIA_INV_REFRESH_FIXTURE", "").strip().lower()
            in ("1", "true", "yes")
        ):
            save_fixture(
                client,
                inv_rect,
                TestInventoryEyes.outline_score,
                occ,
                count,
                proto,
            )
            TestInventoryEyes._record("fixture refreshed: PASS")

    def test_identify_items(self) -> None:
        assert TestInventoryEyes.client is not None
        if TestInventoryEyes.inv_rect is None or TestInventoryEyes.occ is None:
            TestInventoryEyes._record(
                "identify items: FAIL (inventory not located — run find/count first)"
            )
            self.fail("inventory not located")

        templates = load_item_templates()
        if not templates:
            TestInventoryEyes._record(
                "identify items: SKIP no templates in %s" % items_directory()
            )
            self.skipTest("no item templates in items/")

        return_diag = os.environ.get("EXODIA_MATCH_DEBUG", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        slot_items, scores, diagnostics = identify_inventory_slot_items(
            TestInventoryEyes.client,
            TestInventoryEyes.inv_rect,
            TestInventoryEyes.occ,
            templates=templates,
            return_diagnostics=return_diag,
        )
        if slot_items is None:
            TestInventoryEyes._record("identify items: FAIL identification grid")
            self.fail("item identification failed")

        TestInventoryEyes.slot_items = slot_items

        identified: List[List[int]] = []
        unknown: List[List[int]] = []
        for row in range(7):
            for col in range(4):
                if not TestInventoryEyes.occ[row][col]:
                    continue
                label = slot_items[row][col]
                score = scores.get((row, col), 0.0)
                diag = (diagnostics or {}).get((row, col), {})
                reject = diag.get("reject", "")
                created = diag.get("created", False)
                is_named = (
                    label
                    and label != "?"
                    and not (label.startswith("unknown:"))
                )
                if is_named:
                    identified.append([row, col])
                    TestInventoryEyes._record(
                        "identify (%d,%d): PASS %s score=%.3f"
                        % (row, col, label, score)
                    )
                else:
                    unknown.append([row, col])
                    if label and label.startswith("unknown:"):
                        extra = " NEW" if created else ""
                        rej = (" reject=%s" % reject) if reject else ""
                        TestInventoryEyes._record(
                            "identify (%d,%d): %s%s score=%.3f%s"
                            % (row, col, label, extra, score, rej)
                        )
                    else:
                        rej = (" reject=%s" % reject) if reject else ""
                        TestInventoryEyes._record(
                            "identify (%d,%d): ? score=%.3f%s" % (row, col, score, rej)
                        )

        TestInventoryEyes._record(
            "identify items: %d known, %d unknown"
            % (len(identified), len(unknown))
        )

        if not TestInventoryEyes.online:
            flax_ok = slot_items[0][0] == "flax"
            TestInventoryEyes._record(
                "flax at (0,0): %s" % ("PASS" if flax_ok else "FAIL")
            )
            self.assertEqual(slot_items[0][0], "flax", "slot (0,0) should be flax")
            for row, col in ((0, 0), (0, 2), (0, 3), (3, 2), (4, 1)):
                self.assertEqual(
                    slot_items[row][col],
                    "flax",
                    "slot (%d,%d) should be flax" % (row, col),
                )
            self.assertEqual(slot_items[1][1], "?", "slot (1,1) should be unknown (coins)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory eyes tests (vision/detection only).")
    parser.add_argument(
        "--online",
        action="store_true",
        help="Capture live client (OSRS visible) instead of reference.png",
    )
    parser.add_argument(
        "--refresh-fixture",
        action="store_true",
        help="With --online: update tests/fixtures/inventory/reference.{png,json}",
    )
    args, _rest = parser.parse_known_args(argv)

    os.chdir(_EXODIA_DIR)
    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    os.environ["EXODIA_INV_TEST_ONLINE"] = "1" if args.online else "0"
    os.environ["EXODIA_INV_REFRESH_FIXTURE"] = "1" if args.refresh_fixture else "0"

    suite = unittest.TestSuite(
        [
            TestInventoryEyes("test_find_inventory"),
            TestInventoryEyes("test_count_items"),
            TestInventoryEyes("test_identify_items"),
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
