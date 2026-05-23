#!/usr/bin/env python3
"""
Inventory screen tests: locate panel, count occupied slots, identify items by template.

Offline (default) — uses ``tests/fixtures/inventory/reference.{png,json}``::

  python tests/bot_inventory_test.py
  python -m unittest tests.bot_inventory_test -v

Online — RuneLite visible, ``client_rect.json``, ``EXODIA_CAPTURE_BACKEND=wsl_ps``::

  python tests/bot_inventory_test.py --online

Online drag test (moves one item to an empty slot — requires items + free space)::

  python tests/bot_inventory_test.py --online

Refresh offline fixture from a live capture (files stay local — not committed)::

  python tests/bot_inventory_test.py --online --refresh-fixture

Writes ``captures/inventory_test_overlay.png`` (gitignored) with grid overlay, drag arrow,
and green PASS/FAIL lines (font size 20) at the top-left of the capture.

Offline runs also write ``captures/offline_inventory_detect.png`` — same style as
``inventory_test_overlay.png`` (occupancy tint + green PASS/FAIL lines) with item
labels on occupied slots (known name or ``?``).
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import json
import os
import random
import time
import unittest
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

import bot_inventory_detect as inv_detect
from bot_inventory_detect import (
    draw_inventory_occupancy_overlay,
    inventory_occupancy_from_client,
    inventory_outline_template_path,
    match_inventory_by_outline,
    validate_inventory_rect,
)
from bot_inventory_items import (
    draw_inventory_item_identify_overlay,
    identify_inventory_slot_items,
    items_directory,
    load_item_templates,
)

_EXODIA_DIR = Path(__file__).resolve().parents[1]
_REFERENCE_DIR = _EXODIA_DIR / "tests" / "fixtures" / "inventory"
_REFERENCE_PNG = _REFERENCE_DIR / "reference.png"
_REFERENCE_JSON = _REFERENCE_DIR / "reference.json"
_OVERLAY_OUT = _EXODIA_DIR / "captures" / "inventory_test_overlay.png"
_OFFLINE_DETECT_OUT = _EXODIA_DIR / "captures" / "offline_inventory_detect.png"

_RESULT_FONT_PX = 20
_RESULT_FONT = cv2.FONT_HERSHEY_SIMPLEX
_RESULT_FONT_SCALE = _RESULT_FONT_PX / 22.0
_RESULT_LINE_STEP = _RESULT_FONT_PX + 6
_RESULT_COLOR_BGR = (0, 255, 0)


def _online_mode() -> bool:
    return os.environ.get("EXODIA_INV_TEST_ONLINE", "").strip().lower() in ("1", "true", "yes")


def draw_test_results_on_image(
    image: np.ndarray,
    lines: Sequence[str],
    *,
    origin: Tuple[int, int] = (0, 0),
    font_px: int = _RESULT_FONT_PX,
) -> np.ndarray:
    """Draw green result lines from the top-left of ``image``."""
    vis = image.copy()
    scale = font_px / 22.0
    line_step = font_px + 6
    x0, y0 = origin
    y = y0 + font_px
    for line in lines:
        cv2.putText(
            vis,
            line,
            (x0, y),
            _RESULT_FONT,
            scale,
            _RESULT_COLOR_BGR,
            1,
            cv2.LINE_AA,
        )
        y += line_step
    return vis


def _inventory_slot_client_center(
    inv_rect: Sequence[int], row: int, col: int
) -> Optional[Tuple[int, int]]:
    from bot_eyes import inventory_cell_inset_px, inventory_grid_cell_xywh

    inset = inventory_cell_inset_px(inv_rect)
    cell = inventory_grid_cell_xywh(tuple(inv_rect), row, col, inset)
    if cell is None:
        return None
    x, y, w, h = cell
    return x + w // 2, y + h // 2


def draw_drag_arrow_on_image(
    image: np.ndarray,
    inv_rect: Sequence[int],
    from_slot: Tuple[int, int],
    to_slot: Tuple[int, int],
) -> np.ndarray:
    """Arrow from original slot center to destination slot center (client-local coords)."""
    vis = image.copy()
    sr, sc = from_slot
    dr, dc = to_slot
    start = _inventory_slot_client_center(inv_rect, sr, sc)
    end = _inventory_slot_client_center(inv_rect, dr, dc)
    if start is None or end is None:
        return vis

    cv2.circle(vis, start, 10, (0, 0, 255), 2)
    cv2.circle(vis, end, 10, (0, 255, 0), 2)
    cv2.arrowedLine(vis, start, end, (0, 255, 255), 3, tipLength=0.25, line_type=cv2.LINE_AA)
    return vis


def _client_screen_center(client_rect: Sequence[int]) -> Tuple[int, int]:
    left, top, w, h = (int(v) for v in client_rect[:4])
    return left + w // 2, top + h // 2


def _move_mouse_to_screen(xy: Tuple[int, int], *, rad: int = 12, duration: float = 0.22) -> None:
    """Move cursor via arms (linear on wsl_ps, same style as drag) and clear hover text."""
    from bot_arms import BotArms

    BotArms().move_mouse(
        [int(xy[0]), int(xy[1])],
        rad=rad,
        duration=duration,
        move_profile="open",
    )
    time.sleep(float(os.environ.get("EXODIA_INV_HOVER_CLEAR_S", "0.35")))


def _capture_client_bgr() -> Tuple[Optional[np.ndarray], Optional[str]]:
    from bot_client_config import load_client_rect
    import bot_env as Env

    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    rect = load_client_rect()
    if not rect or len(rect) != 4:
        return None, "missing or invalid client_rect.json"
    left, top, w, h = (int(v) for v in rect)
    try:
        bgr = Env._grab_bgr_sync(left, top, w, h)
    except Exception as exc:
        return None, "capture failed: %s" % exc
    if bgr is None or bgr.size == 0:
        return None, "capture returned empty frame"
    if float(bgr.mean()) < 8.0:
        return None, "capture looks blank (mean pixel %.1f)" % float(bgr.mean())
    return bgr, None


def _load_offline_client() -> Tuple[Optional[np.ndarray], Optional[Dict[str, Any]], Optional[str]]:
    if not _REFERENCE_PNG.is_file() or not _REFERENCE_JSON.is_file():
        return None, None, "missing tests/fixtures/inventory/reference.{png,json}"
    client = cv2.imread(str(_REFERENCE_PNG))
    if client is None or client.size == 0:
        return None, None, "could not read reference.png"
    meta = json.loads(_REFERENCE_JSON.read_text(encoding="utf-8"))
    return client, meta, None


def _save_fixture(
    client: np.ndarray,
    inv_rect: List[int],
    score: float,
    occ: List[List[bool]],
    count: int,
    proto: Optional[List[float]],
) -> None:
    from bot_eyes import inventory_grid_cell_xywh, inventory_grid_layout

    _REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(_REFERENCE_PNG), client)
    dx, dy, tw, th, gx, gy, gw, gh = inventory_grid_layout(inv_rect)
    s00 = inventory_grid_cell_xywh(tuple(inv_rect), 0, 0, 0)
    meta = {
        "inventory_rect_client_local": [int(v) for v in inv_rect],
        "outline_score": float(score),
        "grid_validation_score": validate_inventory_rect(client, inv_rect),
        "grid_layout": {"offset": [dx, dy], "tile": [tw, th], "gap": [gx, gy], "field": [gw, gh]},
        "slot_0_0": list(s00) if s00 else None,
        "empty_prototype_bgr": proto,
        "occupied_count": int(count),
        "occupancy": occ,
        "occupied_slots": [[r, c] for r in range(7) for c in range(4) if occ[r][c]],
    }
    _REFERENCE_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _parse_slot_env(key: str) -> Optional[Tuple[int, int]]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.replace(":", ",").split(",") if p.strip()]
    if len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def _random_slot(
    occ: List[List[bool]],
    *,
    occupied: bool,
    exclude: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int]]:
    slots = [
        (row, col)
        for row in range(7)
        for col in range(4)
        if occ[row][col] == occupied and (exclude is None or (row, col) != exclude)
    ]
    if not slots:
        return None
    return random.choice(slots)


class TestInventoryScreen(unittest.TestCase):
    """Find inventory on screen, then count how many slots have items."""

    client: Optional[np.ndarray] = None
    meta: Optional[Dict[str, Any]] = None
    inv_rect: Optional[List[int]] = None
    outline_score: float = 0.0
    grid_score: float = 0.0
    occ: Optional[List[List[bool]]] = None
    item_count: int = 0
    result_lines: List[str] = []
    online: bool = False
    drag_from_slot: Optional[Tuple[int, int]] = None
    drag_to_slot: Optional[Tuple[int, int]] = None
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
        cls.drag_from_slot = None
        cls.drag_to_slot = None
        cls.slot_items = None
        cls.online = _online_mode()
        cls._record("mode: %s" % ("online" if cls.online else "offline"))

        if not inventory_outline_template_path().is_file():
            raise unittest.SkipTest("missing inventory outline template")

        if cls.online:
            client, err = _capture_client_bgr()
            if client is None:
                raise unittest.SkipTest(err or "could not capture client frame")
            cls.meta = None
        else:
            client, meta, err = _load_offline_client()
            if client is None:
                raise unittest.SkipTest(err or "offline reference missing")
            cls.meta = meta

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

        if (
            cls.inv_rect is not None
            and cls.drag_from_slot is not None
            and cls.drag_to_slot is not None
        ):
            overlay = draw_drag_arrow_on_image(
                overlay, cls.inv_rect, cls.drag_from_slot, cls.drag_to_slot
            )

        overlay = draw_test_results_on_image(overlay, cls.result_lines)
        _OVERLAY_OUT.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_OVERLAY_OUT), overlay)

        print("\ninventory overlay: %s" % _OVERLAY_OUT)
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
        assert TestInventoryScreen.client is not None
        client = TestInventoryScreen.client

        matched = match_inventory_by_outline(client)
        if matched is None:
            TestInventoryScreen._record("find inventory: FAIL outline match")
            self.fail("inventory outline match failed")

        inv_rect, score = matched
        TestInventoryScreen.inv_rect = list(inv_rect)
        TestInventoryScreen.outline_score = float(score)

        min_score = float(os.environ.get("EXODIA_INV_OUTLINE_MIN_SCORE", "0.55"))
        outline_ok = score >= min_score
        TestInventoryScreen._record(
            "find inventory: %s rect=%s score=%.3f"
            % ("PASS" if outline_ok else "FAIL", inv_rect, score)
        )
        self.assertGreaterEqual(score, min_score)

        grid_score = validate_inventory_rect(client, inv_rect)
        TestInventoryScreen.grid_score = float(grid_score)
        min_grid = float(os.environ.get("EXODIA_INV_MIN_GRID_SCORE", "12"))
        grid_ok = grid_score >= min_grid
        TestInventoryScreen._record(
            "grid validation: %s score=%.1f" % ("PASS" if grid_ok else "FAIL", grid_score)
        )
        self.assertGreaterEqual(grid_score, min_grid)

        fx, fy, fw, fh = inv_rect
        h0, w0 = client.shape[:2]
        in_bounds = fx > 0 and fy > 0 and fx + fw < w0 + 4 and fy + fh < h0 + 4
        TestInventoryScreen._record(
            "inventory in frame: %s" % ("PASS" if in_bounds else "FAIL")
        )
        self.assertGreater(fx, 0)
        self.assertGreater(fy, 0)
        self.assertLess(fx + fw, w0 + 4)
        self.assertLess(fy + fh, h0 + 4)

        if not TestInventoryScreen.online and TestInventoryScreen.meta is not None:
            expected = TestInventoryScreen.meta["inventory_rect_client_local"]
            tol = int(os.environ.get("EXODIA_INV_REF_TOL_PX", "8"))
            rect_ok = all(abs(inv_rect[i] - expected[i]) <= tol for i in range(4))
            TestInventoryScreen._record(
                "rect vs reference: %s tol=%dpx" % ("PASS" if rect_ok else "FAIL", tol)
            )
            for i in range(4):
                self.assertLessEqual(abs(inv_rect[i] - expected[i]), tol)

    def test_count_items(self) -> None:
        assert TestInventoryScreen.client is not None
        if TestInventoryScreen.inv_rect is None:
            matched = match_inventory_by_outline(TestInventoryScreen.client)
            if matched is None:
                TestInventoryScreen._record("count items: FAIL (inventory not found)")
                self.fail("inventory not located")
            inv_rect, _score = matched
            TestInventoryScreen.inv_rect = list(inv_rect)

        client = TestInventoryScreen.client
        inv_rect = TestInventoryScreen.inv_rect

        occ, count, proto = inventory_occupancy_from_client(client, inv_rect)
        if occ is None:
            TestInventoryScreen._record("count items: FAIL occupancy grid")
            self.fail("occupancy detection failed")

        TestInventoryScreen.occ = occ
        TestInventoryScreen.item_count = int(count)

        count_ok = 0 <= count <= 28
        filled = [[r, c] for r in range(7) for c in range(4) if occ[r][c]]
        TestInventoryScreen._record(
            "count items: %s %d / 28 occupied %s"
            % ("PASS" if count_ok else "FAIL", count, filled)
        )
        self.assertGreaterEqual(count, 0)
        self.assertLessEqual(count, 28)

        if TestInventoryScreen.online:
            raw_expect = os.environ.get("EXODIA_INV_EXPECT_COUNT", "").strip()
            if raw_expect:
                expect = int(raw_expect)
                expect_ok = count == expect
                TestInventoryScreen._record(
                    "expected count: %s want=%d got=%d"
                    % ("PASS" if expect_ok else "FAIL", expect, count)
                )
                self.assertEqual(count, expect)
        elif TestInventoryScreen.meta is not None:
            expect = int(TestInventoryScreen.meta["occupied_count"])
            expect_ok = count == expect
            TestInventoryScreen._record(
                "count vs reference: %s want=%d got=%d"
                % ("PASS" if expect_ok else "FAIL", expect, count)
            )
            self.assertEqual(count, expect)

        if (
            TestInventoryScreen.online
            and os.environ.get("EXODIA_INV_REFRESH_FIXTURE", "").strip().lower()
            in ("1", "true", "yes")
        ):
            _save_fixture(
                client,
                inv_rect,
                TestInventoryScreen.outline_score,
                occ,
                count,
                proto,
            )
            TestInventoryScreen._record("fixture refreshed: PASS")

    def test_identify_items(self) -> None:
        assert TestInventoryScreen.client is not None
        if TestInventoryScreen.inv_rect is None or TestInventoryScreen.occ is None:
            matched = match_inventory_by_outline(TestInventoryScreen.client)
            if matched is None:
                TestInventoryScreen._record("identify items: FAIL inventory not found")
                self.fail("inventory not located")
            inv_rect, _score = matched
            TestInventoryScreen.inv_rect = list(inv_rect)
            occ, _count, _proto = inventory_occupancy_from_client(
                TestInventoryScreen.client, TestInventoryScreen.inv_rect
            )
            if occ is None:
                TestInventoryScreen._record("identify items: FAIL occupancy grid")
                self.fail("occupancy detection failed")
            TestInventoryScreen.occ = occ

        templates = load_item_templates()
        if not templates:
            TestInventoryScreen._record(
                "identify items: SKIP no templates in %s" % items_directory()
            )
            self.skipTest("no item templates in items/")

        slot_items, scores = identify_inventory_slot_items(
            TestInventoryScreen.client,
            TestInventoryScreen.inv_rect,
            TestInventoryScreen.occ,
            templates=templates,
        )
        if slot_items is None:
            TestInventoryScreen._record("identify items: FAIL identification grid")
            self.fail("item identification failed")

        TestInventoryScreen.slot_items = slot_items

        identified: List[List[int]] = []
        unknown: List[List[int]] = []
        for row in range(7):
            for col in range(4):
                if not TestInventoryScreen.occ[row][col]:
                    continue
                label = slot_items[row][col]
                score = scores.get((row, col), 0.0)
                if label and label != "?":
                    identified.append([row, col])
                    TestInventoryScreen._record(
                        "identify (%d,%d): PASS %s score=%.3f"
                        % (row, col, label, score)
                    )
                else:
                    unknown.append([row, col])
                    TestInventoryScreen._record(
                        "identify (%d,%d): ? score=%.3f" % (row, col, score)
                    )

        TestInventoryScreen._record(
            "identify items: %d known, %d unknown"
            % (len(identified), len(unknown))
        )

        if not TestInventoryScreen.online:
            flax_ok = slot_items[0][0] == "flax"
            TestInventoryScreen._record(
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

    def test_drag_item_to_empty_slot(self) -> None:
        if not _online_mode():
            self.skipTest("online only — drags an item in the live client")

        from bot_arms import BotArms
        from bot_client_config import load_client_rect
        from bot_eyes import INV_COLS, INV_ROWS, inventory_slot_screen_xy
        import bot_env as Env

        client_rect = load_client_rect()
        if not client_rect or len(client_rect) != 4:
            self.skipTest("missing client_rect.json")

        center_xy = _client_screen_center(client_rect)
        Env.wsl_windows_focus_window("RuneLite")
        time.sleep(0.35)
        _move_mouse_to_screen(center_xy)

        client, err = _capture_client_bgr()
        if client is None:
            self.skipTest(err or "could not capture client frame")

        matched = match_inventory_by_outline(client)
        if matched is None:
            TestInventoryScreen._record("drag item: FAIL inventory not found")
            self.fail("inventory outline match failed")
        inv_rect, _score = matched
        inv_rect = list(inv_rect)

        occ, count, _proto = inventory_occupancy_from_client(client, inv_rect)
        if occ is None:
            TestInventoryScreen._record("drag item: FAIL occupancy grid")
            self.fail("occupancy detection failed")

        src = _parse_slot_env("EXODIA_INV_DRAG_FROM") or _random_slot(occ, occupied=True)
        dst = _parse_slot_env("EXODIA_INV_DRAG_TO") or _random_slot(
            occ, occupied=False, exclude=src
        )
        if src is None:
            self.skipTest("no occupied slot to drag from")
        if dst is None:
            self.skipTest("no empty slot to drag to")
        if src == dst:
            self.skipTest("source and destination slots are the same")

        sr, sc = src
        dr, dc = dst
        if not (0 <= sr < INV_ROWS and 0 <= sc < INV_COLS and 0 <= dr < INV_ROWS and 0 <= dc < INV_COLS):
            self.fail("slot out of range")
        if not occ[sr][sc]:
            TestInventoryScreen._record("drag item: FAIL source (%d,%d) empty" % (sr, sc))
            self.fail("source slot is empty")
        if occ[dr][dc]:
            TestInventoryScreen._record("drag item: FAIL dest (%d,%d) occupied" % (dr, dc))
            self.fail("destination slot is occupied")

        start_xy = inventory_slot_screen_xy(inv_rect, client_rect, sr, sc)
        end_xy = inventory_slot_screen_xy(inv_rect, client_rect, dr, dc)
        if start_xy is None or end_xy is None:
            TestInventoryScreen._record("drag item: FAIL slot screen coords")
            self.fail("could not resolve slot screen coordinates")

        TestInventoryScreen.drag_from_slot = (sr, sc)
        TestInventoryScreen.drag_to_slot = (dr, dc)

        drag_rad = int(os.environ.get("EXODIA_INV_DRAG_RAD", "4"))
        BotArms().drag_at(start_xy, end_xy, rad=drag_rad, duration=0.28)

        _move_mouse_to_screen(center_xy)

        settle_s = float(os.environ.get("EXODIA_INV_DRAG_SETTLE_S", "1.0"))
        time.sleep(max(0.2, settle_s))

        after, err = _capture_client_bgr()
        if after is None:
            TestInventoryScreen._record("drag item: FAIL post-drag capture")
            self.fail(err or "post-drag capture failed")

        occ_after, count_after, _ = inventory_occupancy_from_client(after, inv_rect)
        if occ_after is None:
            TestInventoryScreen._record("drag item: FAIL post-drag occupancy")
            self.fail("post-drag occupancy failed")

        moved_ok = (
            not occ_after[sr][sc]
            and occ_after[dr][dc]
            and count_after == count
        )
        TestInventoryScreen._record(
            "drag item: %s (%d,%d)->(%d,%d) screen %s->%s count=%d"
            % (
                "PASS" if moved_ok else "FAIL",
                sr,
                sc,
                dr,
                dc,
                start_xy,
                end_xy,
                count_after,
            )
        )
        TestInventoryScreen.client = after
        TestInventoryScreen.inv_rect = inv_rect
        TestInventoryScreen.occ = occ_after
        TestInventoryScreen.item_count = int(count_after)

        self.assertFalse(occ_after[sr][sc], "source slot still occupied")
        self.assertTrue(occ_after[dr][dc], "destination slot still empty")
        self.assertEqual(count_after, count, "occupied slot count changed")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory locate + item count tests.")
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
    args, rest = parser.parse_known_args(argv)

    os.chdir(_EXODIA_DIR)
    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    os.environ["EXODIA_INV_TEST_ONLINE"] = "1" if args.online else "0"
    os.environ["EXODIA_INV_REFRESH_FIXTURE"] = "1" if args.refresh_fixture else "0"
    if args.online:
        os.environ.setdefault("EXODIA_INPUT_BACKEND", "wsl_ps")

    suite = unittest.TestSuite(
        [
            TestInventoryScreen("test_find_inventory"),
            TestInventoryScreen("test_count_items"),
            TestInventoryScreen("test_identify_items"),
            TestInventoryScreen("test_drag_item_to_empty_slot"),
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
