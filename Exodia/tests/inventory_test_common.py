"""Shared helpers for inventory eyes and arms integration tests."""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_inventory_actions import clear_inventory_hover
from bot_inventory_detect import (
    bind_inventory_to_eyes,
    inventory_occupancy_from_client,
    match_inventory_by_outline,
    validate_inventory_rect,
)

_EXODIA_DIR = Path(__file__).resolve().parents[1]
_REFERENCE_DIR = _EXODIA_DIR / "tests" / "fixtures" / "inventory"
_REFERENCE_PNG = _REFERENCE_DIR / "reference.png"
_REFERENCE_JSON = _REFERENCE_DIR / "reference.json"

_RESULT_FONT_PX = 20
_RESULT_FONT = cv2.FONT_HERSHEY_SIMPLEX
_RESULT_COLOR_BGR = (0, 255, 0)


def exodia_dir() -> Path:
    return _EXODIA_DIR


def reference_paths() -> Tuple[Path, Path]:
    return _REFERENCE_PNG, _REFERENCE_JSON


def online_mode() -> bool:
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


def inventory_slot_client_center(
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
    start = inventory_slot_client_center(inv_rect, sr, sc)
    end = inventory_slot_client_center(inv_rect, dr, dc)
    if start is None or end is None:
        return vis

    cv2.circle(vis, start, 10, (0, 0, 255), 2)
    cv2.circle(vis, end, 10, (0, 255, 0), 2)
    cv2.arrowedLine(vis, start, end, (0, 255, 255), 3, tipLength=0.25, line_type=cv2.LINE_AA)
    return vis


def capture_client_bgr() -> Tuple[Optional[np.ndarray], Optional[str]]:
    from bot_client_config import load_client_rect
    from bot_capture import capture_client_pristine

    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    rect = load_client_rect()
    if not rect or len(rect) != 4:
        return None, "missing or invalid client_rect.json"
    try:
        bgr = capture_client_pristine(rect)
    except Exception as exc:
        return None, "capture failed: %s" % exc
    if bgr is None or bgr.size == 0:
        return None, "capture returned empty frame"
    if float(bgr.mean()) < 8.0:
        return None, "capture looks blank (mean pixel %.1f)" % float(bgr.mean())
    return bgr, None


def inventory_test_eyes(
    client: np.ndarray,
    *,
    client_rect: Optional[Sequence[int]] = None,
):
    """``BotEyes`` with ``curr_client`` set for ``bind_inventory_to_eyes`` tests."""
    from bot_eyes import BotEyes

    h, w = client.shape[:2]
    if client_rect is None:
        from bot_client_config import load_client_rect

        client_rect = load_client_rect()
    if not client_rect or len(client_rect) != 4:
        client_rect = [0, 0, w, h]
    eyes = BotEyes(win_rect=[int(v) for v in client_rect], DEBUG=False)
    eyes.curr_client = client
    return eyes


def locate_inventory_rect(
    client: np.ndarray,
) -> Tuple[Optional[List[int]], float, float]:
    """
    Bind inventory panel on ``client`` via ``bind_inventory_to_eyes`` — must succeed
    before count/identify.

    Returns ``(rect, outline_score_at_rect, grid_score)``.
    """
    eyes = inventory_test_eyes(client)
    rect = bind_inventory_to_eyes(eyes, refresh_client=False, force=True)
    if not rect or len(rect) != 4:
        return None, 0.0, 0.0
    grid = float(validate_inventory_rect(client, rect))
    outline_score = 0.0
    try:
        from bot_inventory_detect import _load_inventory_outline_assets

        assets = _load_inventory_outline_assets()
        if assets is not None:
            _template, gray_tpl, mask = assets
            th, tw = gray_tpl.shape[:2]
            ix, iy = int(rect[0]), int(rect[1])
            if iy + th <= client.shape[0] and ix + tw <= client.shape[1] and iy >= 0 and ix >= 0:
                patch = cv2.cvtColor(client[iy : iy + th, ix : ix + tw], cv2.COLOR_BGR2GRAY)
                res = cv2.matchTemplate(patch, gray_tpl, cv2.TM_CCORR_NORMED, mask=mask)
                outline_score = float(res[0, 0])
    except Exception:
        outline_score = 0.0
    return list(rect), outline_score, grid


def load_offline_client() -> Tuple[Optional[np.ndarray], Optional[Dict[str, Any]], Optional[str]]:
    if not _REFERENCE_PNG.is_file() or not _REFERENCE_JSON.is_file():
        return None, None, "missing tests/fixtures/inventory/reference.{png,json}"
    client = cv2.imread(str(_REFERENCE_PNG))
    if client is None or client.size == 0:
        return None, None, "could not read reference.png"
    meta = json.loads(_REFERENCE_JSON.read_text(encoding="utf-8"))
    return client, meta, None


def save_fixture(
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


def parse_slot_env(key: str) -> Optional[Tuple[int, int]]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.replace(":", ",").split(",") if p.strip()]
    if len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def random_slot(
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


def drag_rounds() -> int:
    raw = os.environ.get("EXODIA_INV_DRAG_ROUNDS", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


@dataclass(frozen=True)
class InventoryDragResult:
    """Outcome of dragging one item between inventory slots."""

    src: Tuple[int, int]
    dst: Tuple[int, int]
    start_xy: Tuple[int, int]
    end_xy: Tuple[int, int]
    count_before: int
    count_after: int
    client_after: np.ndarray
    inv_rect: List[int]
    occ_after: List[List[bool]]


def perform_inventory_drag(
    inv_rect: Sequence[int],
    occ: List[List[bool]],
    count: int,
    *,
    src: Optional[Tuple[int, int]] = None,
    dst: Optional[Tuple[int, int]] = None,
    focus_client: bool = False,
) -> InventoryDragResult:
    """Drag occupied slot → empty slot; return post-drag capture."""
    from bot_arms import BotArms
    from bot_client_config import load_client_rect
    from bot_eyes import INV_COLS, INV_ROWS, inventory_slot_screen_xy
    import bot_env as Env

    client_rect = load_client_rect()
    if not client_rect or len(client_rect) != 4:
        raise RuntimeError("missing client_rect.json")

    if focus_client:
        Env.wsl_windows_focus_window("RuneLite")
        time.sleep(0.35)
    clear_inventory_hover(client_rect)

    src_slot = src or parse_slot_env("EXODIA_INV_DRAG_FROM") or random_slot(occ, occupied=True)
    dst_slot = dst or parse_slot_env("EXODIA_INV_DRAG_TO") or random_slot(
        occ, occupied=False, exclude=src_slot
    )
    if src_slot is None:
        raise RuntimeError("no occupied slot to drag from")
    if dst_slot is None:
        raise RuntimeError("no empty slot to drag to")
    if src_slot == dst_slot:
        raise RuntimeError("source and destination slots are the same")

    sr, sc = src_slot
    dr, dc = dst_slot
    if not (
        0 <= sr < INV_ROWS
        and 0 <= sc < INV_COLS
        and 0 <= dr < INV_ROWS
        and 0 <= dc < INV_COLS
    ):
        raise RuntimeError("slot out of range")
    if not occ[sr][sc]:
        raise RuntimeError("source slot (%d,%d) is empty" % (sr, sc))
    if occ[dr][dc]:
        raise RuntimeError("destination slot (%d,%d) is occupied" % (dr, dc))

    start_xy = inventory_slot_screen_xy(inv_rect, client_rect, sr, sc)
    end_xy = inventory_slot_screen_xy(inv_rect, client_rect, dr, dc)
    if start_xy is None or end_xy is None:
        raise RuntimeError("could not resolve slot screen coordinates")

    drag_rad = int(os.environ.get("EXODIA_INV_DRAG_RAD", "4"))
    BotArms().drag_at(start_xy, end_xy, rad=drag_rad, duration=0.28)
    clear_inventory_hover(client_rect)

    settle_s = float(os.environ.get("EXODIA_INV_DRAG_SETTLE_S", "1.0"))
    time.sleep(max(0.2, settle_s))

    after, err = capture_client_bgr()
    if after is None:
        raise RuntimeError(err or "post-drag capture failed")

    matched = match_inventory_by_outline(after)
    if matched is None:
        raise RuntimeError("post-drag inventory outline match failed")
    inv_after, _score = matched
    inv_after = list(inv_after)

    occ_after, count_after, _proto = inventory_occupancy_from_client(after, inv_after)
    if occ_after is None:
        raise RuntimeError("post-drag occupancy failed")

    return InventoryDragResult(
        src=(sr, sc),
        dst=(dr, dc),
        start_xy=start_xy,
        end_xy=end_xy,
        count_before=int(count),
        count_after=int(count_after),
        client_after=after,
        inv_rect=inv_after,
        occ_after=occ_after,
    )


def configure_online_env() -> None:
    os.chdir(_EXODIA_DIR)
    os.environ.setdefault("EXODIA_CAPTURE_BACKEND", "wsl_ps")
    os.environ.setdefault("EXODIA_INPUT_BACKEND", "wsl_ps")
