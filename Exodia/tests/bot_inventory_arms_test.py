#!/usr/bin/env python3
"""
Inventory **arms** tests — mouse input (drag items between slots).

Online only — RuneLite visible, ``client_rect.json``, ``EXODIA_CAPTURE_BACKEND=wsl_ps``::

  python tests/bot_inventory_arms_test.py --online

Eyes/detection tests (no input) are separate::

  python tests/bot_inventory_test.py [--online]

Uses vision only to **verify** drags (occupancy before/after); does not test template identify.

Env:
  EXODIA_INV_DRAG_FROM / EXODIA_INV_DRAG_TO — force ``row,col`` slots
  EXODIA_INV_DRAG_ROUNDS — number of consecutive drags (default ``1``)
  EXODIA_INV_DRAG_SETTLE_S — wait after each drag before re-capture (default ``1.0``)

Writes ``captures/inventory_arms_overlay.png`` with drag arrow(s) and PASS/FAIL lines.
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
from typing import List, Optional, Tuple

import cv2
import numpy as np

import bot_inventory_detect as inv_detect
from bot_inventory_detect import (
    draw_inventory_occupancy_overlay,
    inventory_occupancy_from_client,
    inventory_outline_template_path,
    match_inventory_by_outline,
)
from tests.inventory_test_common import (
    InventoryDragResult,
    capture_client_bgr,
    configure_online_env,
    draw_drag_arrow_on_image,
    draw_test_results_on_image,
    drag_rounds,
    exodia_dir,
    perform_inventory_drag,
)

_EXODIA_DIR = exodia_dir()
_OVERLAY_OUT = _EXODIA_DIR / "captures" / "inventory_arms_overlay.png"


class TestInventoryArms(unittest.TestCase):
    """Drag items between inventory slots; verify with occupancy detection."""

    client: Optional[np.ndarray] = None
    inv_rect: Optional[List[int]] = None
    occ: Optional[List[List[bool]]] = None
    item_count: int = 0
    result_lines: List[str] = []
    drag_moves: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []

    @classmethod
    def _record(cls, line: str) -> None:
        cls.result_lines.append(line)

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("EXODIA_INV_ARMS_TEST", "").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            raise unittest.SkipTest(
                "arms tests — run: python tests/bot_inventory_arms_test.py --online"
            )
        configure_online_env()
        os.environ["EXODIA_INV_CALIB_USE_EEL"] = "0"
        inv_detect._outline_cache = None
        cls.result_lines = []
        cls.drag_moves = []
        cls._record("suite: arms")
        cls._record("mode: online")

        if not inventory_outline_template_path().is_file():
            raise unittest.SkipTest("missing inventory outline template")

        client, err = capture_client_bgr()
        if client is None:
            raise unittest.SkipTest(err or "could not capture client frame")
        cls.client = client

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.client is None:
            return

        if cls.inv_rect is not None and cls.occ is not None:
            overlay = draw_inventory_occupancy_overlay(cls.client, cls.inv_rect, cls.occ)
        elif cls.inv_rect is not None:
            overlay = draw_inventory_occupancy_overlay(cls.client, cls.inv_rect)
        else:
            overlay = cls.client.copy()

        for src, dst in cls.drag_moves:
            overlay = draw_drag_arrow_on_image(overlay, cls.inv_rect, src, dst)

        overlay = draw_test_results_on_image(overlay, cls.result_lines)
        _OVERLAY_OUT.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_OVERLAY_OUT), overlay)

        print("\ninventory arms overlay: %s" % _OVERLAY_OUT)
        for line in cls.result_lines:
            print("  %s" % line)

    def _assert_drag_move(self, drag: InventoryDragResult, *, label: str) -> None:
        sr, sc = drag.src
        dr, dc = drag.dst
        moved_ok = (
            not drag.occ_after[sr][sc]
            and drag.occ_after[dr][dc]
            and drag.count_after == drag.count_before
        )
        TestInventoryArms._record(
            "%s: %s (%d,%d)->(%d,%d) screen %s->%s count=%d"
            % (
                label,
                "PASS" if moved_ok else "FAIL",
                sr,
                sc,
                dr,
                dc,
                drag.start_xy,
                drag.end_xy,
                drag.count_after,
            )
        )
        self.assertFalse(drag.occ_after[sr][sc], "%s: source still occupied" % label)
        self.assertTrue(drag.occ_after[dr][dc], "%s: destination still empty" % label)
        self.assertEqual(
            drag.count_after,
            drag.count_before,
            "%s: occupied slot count changed" % label,
        )
        TestInventoryArms.client = drag.client_after
        TestInventoryArms.inv_rect = drag.inv_rect
        TestInventoryArms.occ = drag.occ_after
        TestInventoryArms.item_count = drag.count_after
        TestInventoryArms.drag_moves.append((drag.src, drag.dst))

    def test_drag_item_to_empty_slot(self) -> None:
        """Drag one occupied slot to an empty slot; verify occupancy moved."""
        assert TestInventoryArms.client is not None

        matched = match_inventory_by_outline(TestInventoryArms.client)
        if matched is None:
            TestInventoryArms._record("drag: FAIL inventory not found")
            self.fail("inventory outline match failed")
        inv_rect, _score = matched
        inv_rect = list(inv_rect)

        occ, count, _proto = inventory_occupancy_from_client(TestInventoryArms.client, inv_rect)
        if occ is None:
            TestInventoryArms._record("drag: FAIL occupancy grid")
            self.fail("occupancy detection failed")

        TestInventoryArms.inv_rect = inv_rect
        TestInventoryArms.occ = occ
        TestInventoryArms.item_count = int(count)

        drag = perform_inventory_drag(inv_rect, occ, count, focus_client=True)
        self._assert_drag_move(drag, label="drag")

    def test_drag_multiple_rounds(self) -> None:
        """Optional extra drags (``EXODIA_INV_DRAG_ROUNDS`` > 1)."""
        rounds = drag_rounds()
        if rounds <= 1:
            self.skipTest("EXODIA_INV_DRAG_ROUNDS <= 1")

        assert TestInventoryArms.client is not None
        assert TestInventoryArms.inv_rect is not None
        assert TestInventoryArms.occ is not None

        prior_dst: Optional[Tuple[int, int]] = (
            TestInventoryArms.drag_moves[-1][1] if TestInventoryArms.drag_moves else None
        )
        for idx in range(2, rounds + 1):
            drag = perform_inventory_drag(
                TestInventoryArms.inv_rect,
                TestInventoryArms.occ,
                TestInventoryArms.item_count,
                src=prior_dst,
            )
            self._assert_drag_move(drag, label="drag round %d" % idx)
            prior_dst = drag.dst


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory arms tests (drag/move items).")
    parser.add_argument(
        "--online",
        action="store_true",
        help="Required — arms tests need a live RuneLite client",
    )
    args, _rest = parser.parse_known_args(argv)
    if not args.online:
        print("Inventory arms tests require --online (live RuneLite client).")
        return 2

    configure_online_env()
    os.environ["EXODIA_INV_TEST_ONLINE"] = "1"
    os.environ["EXODIA_INV_ARMS_TEST"] = "1"

    suite = unittest.TestSuite(
        [
            TestInventoryArms("test_drag_item_to_empty_slot"),
            TestInventoryArms("test_drag_multiple_rounds"),
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
