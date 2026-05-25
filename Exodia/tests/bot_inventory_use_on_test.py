#!/usr/bin/env python3
"""
Inventory use-on test — click hammer, then infernal eel (online only).

Requires RuneLite visible, ``client_rect.json``, and both items in inventory::

  python tests/bot_inventory_use_on_test.py --online

Env:
  EXODIA_USE_ON_SOURCE — source item stem (default ``hammer``)
  EXODIA_USE_ON_DEST   — destination item stem (default ``infernal_eel``)
  EXODIA_USE_ON_SETTLE_S — wait after click before re-capture (default ``1.5``)

Writes ``captures/inventory_use_on_overlay.png`` with the click arrow and result lines.
You decide whether the in-game action succeeded.
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import os
import time
import unittest
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2

import bot_inventory_detect as inv_detect
from bot_inventory_actions import slots_matching_item, use_named_item_on_named_item
from bot_inventory_detect import (
    draw_inventory_occupancy_overlay,
    inventory_occupancy_from_client,
    inventory_outline_template_path,
    match_inventory_by_outline,
)
from bot_inventory_items import count_labeled_item_slots, identify_inventory_slot_items
from tests.inventory_test_common import (
    capture_client_bgr,
    configure_online_env,
    draw_drag_arrow_on_image,
    draw_test_results_on_image,
    exodia_dir,
)

_EXODIA_DIR = exodia_dir()
_OVERLAY_OUT = _EXODIA_DIR / "captures" / "inventory_use_on_overlay.png"


def _source_item() -> str:
    return os.environ.get("EXODIA_USE_ON_SOURCE", "hammer").strip().lower()


def _dest_item() -> str:
    return os.environ.get("EXODIA_USE_ON_DEST", "infernal_eel").strip().lower()


@dataclass(frozen=True)
class UseOnAttempt:
    source_slot: Tuple[int, int]
    dest_slot: Tuple[int, int]
    eel_slots_before: int
    eel_slots_after: int
    ok: bool
    reason: str


class TestInventoryUseOn(unittest.TestCase):
    """Use hammer on infernal eel when both are visible in inventory."""

    client: Optional[np.ndarray] = None
    inv_rect: Optional[List[int]] = None
    result_lines: List[str] = []
    use_on_move: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None

    @classmethod
    def _record(cls, line: str) -> None:
        cls.result_lines.append(line)

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("EXODIA_INV_USE_ON_TEST", "").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            raise unittest.SkipTest(
                "use-on test — run: python tests/bot_inventory_use_on_test.py --online"
            )
        configure_online_env()
        inv_detect._outline_cache = None
        cls.result_lines = ["suite: use-on", "mode: online"]
        cls.use_on_move = None

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
        overlay = cls.client.copy()
        if cls.inv_rect is not None:
            overlay = draw_inventory_occupancy_overlay(overlay, cls.inv_rect)
        if cls.use_on_move is not None and cls.inv_rect is not None:
            overlay = draw_drag_arrow_on_image(overlay, cls.inv_rect, *cls.use_on_move)
        overlay = draw_test_results_on_image(overlay, cls.result_lines)
        _OVERLAY_OUT.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_OVERLAY_OUT), overlay)
        print("\ninventory use-on overlay: %s" % _OVERLAY_OUT)
        for line in cls.result_lines:
            print("  %s" % line)

    def test_use_hammer_on_infernal_eel(self) -> None:
        """Click source item on destination when both are labeled in inventory."""
        assert TestInventoryUseOn.client is not None

        matched = match_inventory_by_outline(TestInventoryUseOn.client)
        if matched is None:
            self._record("use-on: SKIP inventory not found")
            self.skipTest("inventory outline match failed")
        inv_rect, _score = matched
        inv_rect = list(inv_rect)
        TestInventoryUseOn.inv_rect = inv_rect

        occ, _count, _proto = inventory_occupancy_from_client(
            TestInventoryUseOn.client, inv_rect
        )
        if occ is None:
            self._record("use-on: SKIP occupancy grid failed")
            self.skipTest("occupancy detection failed")

        slot_items, _scores, _diag = identify_inventory_slot_items(
            TestInventoryUseOn.client,
            inv_rect,
            occ,
            frame_buckets=True,
        )
        if slot_items is None:
            self._record("use-on: SKIP item identify failed")
            self.skipTest("identify_inventory_slot_items failed")

        source_item = _source_item()
        dest_item = _dest_item()

        hammer_slots = slots_matching_item(slot_items, source_item)
        eel_slots = slots_matching_item(slot_items, dest_item)
        eel_before = count_labeled_item_slots(slot_items, occ, dest_item)

        self._record(
            "seen: %s=%d slot(s) %s=%d slot(s)"
            % (source_item, len(hammer_slots), dest_item, len(eel_slots))
        )
        if not hammer_slots:
            self._record("use-on: SKIP no %s in inventory" % source_item)
            self.skipTest("no %s visible" % source_item)
        if not eel_slots:
            self._record("use-on: SKIP no %s in inventory" % dest_item)
            self.skipTest("no %s visible" % dest_item)

        from bot_client_config import load_client_rect
        import bot_env as Env

        client_rect = load_client_rect()
        if not client_rect or len(client_rect) != 4:
            self.fail("missing client_rect.json")

        Env.wsl_windows_focus_window("RuneLite")
        time.sleep(0.35)

        result = use_named_item_on_named_item(
            inv_rect,
            client_rect,
            slot_items,
            source_item,
            dest_item,
        )
        attempt = UseOnAttempt(
            source_slot=result.source_slot or hammer_slots[0],
            dest_slot=result.dest_slot or eel_slots[0],
            eel_slots_before=eel_before,
            eel_slots_after=eel_before,
            ok=bool(result.ok),
            reason=result.reason if result.ok else (result.reason or "unknown"),
        )
        if result.ok and result.source_slot and result.dest_slot:
            TestInventoryUseOn.use_on_move = (result.source_slot, result.dest_slot)

        settle_s = float(os.environ.get("EXODIA_USE_ON_SETTLE_S", "1.5"))
        time.sleep(max(0.3, settle_s))

        after, err = capture_client_bgr()
        eel_after = eel_before
        if after is not None:
            TestInventoryUseOn.client = after
            matched_after = match_inventory_by_outline(after)
            if matched_after is not None:
                inv_after, _ = matched_after
                occ_after, _, _ = inventory_occupancy_from_client(after, list(inv_after))
                if occ_after is not None:
                    labels_after, _, _ = identify_inventory_slot_items(
                        after, list(inv_after), occ_after, frame_buckets=True
                    )
                    if labels_after is not None:
                        eel_after = count_labeled_item_slots(labels_after, occ_after, dest_item)
            attempt = UseOnAttempt(
                source_slot=attempt.source_slot,
                dest_slot=attempt.dest_slot,
                eel_slots_before=eel_before,
                eel_slots_after=eel_after,
                ok=attempt.ok,
                reason=attempt.reason,
            )
        elif err:
            self._record("post-capture: %s" % err)

        sr, sc = attempt.source_slot
        dr, dc = attempt.dest_slot
        self._record(
            "use-on: %s (%d,%d)->(%d,%d) reason=%s eels %d->%d"
            % (
                "CLICKED" if attempt.ok else "FAILED",
                sr,
                sc,
                dr,
                dc,
                attempt.reason,
                attempt.eel_slots_before,
                attempt.eel_slots_after,
            )
        )
        self.assertTrue(
            attempt.ok,
            "use-on returned %s (%s)" % (attempt.reason, result.missing_item),
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory use-on test (hammer → infernal eel)."
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Required — needs live RuneLite with hammer and infernal eel visible",
    )
    args, _rest = parser.parse_known_args(argv)
    if not args.online:
        print("Inventory use-on test requires --online (live RuneLite client).")
        return 2

    configure_online_env()
    os.environ["EXODIA_INV_TEST_ONLINE"] = "1"
    os.environ["EXODIA_INV_USE_ON_TEST"] = "1"

    suite = unittest.TestSuite([TestInventoryUseOn("test_use_hammer_on_infernal_eel")])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
