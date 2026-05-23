"""
Live and saved debug overlays for Exodia perception (client-local BGR).

Does not draw on the RuneLite window itself — shows a separate OpenCV window and/or
writes annotated PNGs under ``logs/diag/``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_frames import annotate_regions

ACTION_LABELS = {
    0: "FISHING (green)",
    1: "IDLE (red)",
    2: "no fishing UI",
}


def _env_bool(key: str, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def draw_bot_overlay(
    bot_e: Any,
    *,
    state: Optional[str] = None,
    eel_count: Optional[int] = None,
    inv_slots: Optional[int] = None,
    action_code: Optional[int] = None,
    spot_clicks: Optional[Sequence[Sequence[int]]] = None,
    last_click: Optional[Sequence[int]] = None,
    last_action: Optional[str] = None,
    draw_inventory_grid: bool = True,
) -> Optional[np.ndarray]:
    """
    Annotated copy of the client frame: ROIs, optional spots, HUD text.

    ``spot_clicks`` / ``last_click`` are **screen** coordinates ``[x, y]``.
    """
    if draw_inventory_grid and bot_e.inventory_rect:
        vis = bot_e.draw_inventory_grid_debug()
    else:
        vis = annotate_regions(bot_e)
    if vis is None:
        base = bot_e.curr_client_unmasked or bot_e.curr_client
        if base is None or base.size == 0:
            return None
        vis = base.copy()

    ox = int(bot_e.client_rect[0]) if bot_e.client_rect else 0
    oy = int(bot_e.client_rect[1]) if bot_e.client_rect else 0

    for pt in spot_clicks or ():
        if len(pt) < 2:
            continue
        lx, ly = int(pt[0]) - ox, int(pt[1]) - oy
        cv2.circle(vis, (lx, ly), 10, (0, 255, 255), 2)
        cv2.drawMarker(vis, (lx, ly), (0, 255, 255), cv2.MARKER_CROSS, 18, 2)

    if last_click and len(last_click) >= 2:
        lx, ly = int(last_click[0]) - ox, int(last_click[1]) - oy
        cv2.circle(vis, (lx, ly), 14, (0, 0, 255), 2)
        cv2.putText(
            vis,
            "last click",
            (lx + 16, ly),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    lines: List[str] = []
    if state:
        lines.append("state: %s" % state)
    if action_code is not None:
        lines.append(
            "action: %s (%s)"
            % (action_code, ACTION_LABELS.get(action_code, "?"))
        )
    if eel_count is not None:
        lines.append("eels: %d" % eel_count)
    if inv_slots is not None:
        lines.append("inv slots: %s" % inv_slots)
    if last_action:
        lines.append("last: %s" % last_action[:60])

    y = 22
    for line in lines:
        cv2.putText(
            vis,
            line,
            (8, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            vis,
            line,
            (8, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )
        y += 22

    return vis


class OverlayViewer:
    """
    Non-blocking OpenCV preview (``cv2.imshow`` + ``waitKey(1)``).

    Requires a working display (WSLg / X11). Also optional PNG mirror under ``logs/diag/``.
    """

    def __init__(
        self,
        *,
        window_name: str = "Exodia overlay",
        save_path: Optional[Path] = None,
        scale_percent: int = 70,
    ) -> None:
        self.window_name = window_name
        self.save_path = save_path
        self.scale_percent = max(25, min(100, int(scale_percent)))
        self._opened = False

    @classmethod
    def from_env(cls, logs_dir: Optional[Path] = None) -> Optional["OverlayViewer"]:
        if not _env_bool("EXODIA_OVERLAY", False):
            return None
        save: Optional[Path] = None
        if _env_bool("EXODIA_OVERLAY_SAVE", True):
            root = logs_dir or Path(__file__).resolve().parent / "logs" / "diag"
            root.mkdir(parents=True, exist_ok=True)
            save = root / "overlay_latest.png"
        scale = int(os.environ.get("EXODIA_OVERLAY_SCALE", "70") or "70")
        return cls(save_path=save, scale_percent=scale)

    def show(self, frame_bgr: Optional[np.ndarray]) -> None:
        if frame_bgr is None or frame_bgr.size == 0:
            return
        if self.save_path is not None:
            cv2.imwrite(str(self.save_path), frame_bgr)
        if not _env_bool("EXODIA_OVERLAY_WINDOW", True):
            return
        display = frame_bgr
        if self.scale_percent != 100:
            display = cv2.resize(
                frame_bgr,
                (0, 0),
                fx=self.scale_percent / 100.0,
                fy=self.scale_percent / 100.0,
                interpolation=cv2.INTER_AREA,
            )
        if not self._opened:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            self._opened = True
        cv2.imshow(self.window_name, display)
        cv2.waitKey(1)

    def close(self) -> None:
        if self._opened:
            try:
                cv2.destroyWindow(self.window_name)
            except Exception:
                pass
            self._opened = False
