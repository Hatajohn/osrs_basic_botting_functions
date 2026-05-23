"""
Cross-platform window lookup for the Exodia layer and repo root core.

Linux/WSLg: uses xdotool (no extra Python deps). Requires `xdotool` on PATH.
Windows: not used here — callers use pywin32 directly.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional, Tuple

Geo = Tuple[int, int, int, int]


def _run(args: List[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def xdotool_available() -> bool:
    return shutil.which("xdotool") is not None


def linux_search_window_id(title_substring: str, only_visible: bool = True) -> Optional[int]:
    """First window ID whose name contains ``title_substring``."""
    if not xdotool_available():
        return None
    for cmd in (
        ["xdotool", "search", "--onlyvisible", "--name", title_substring],
        ["xdotool", "search", "--name", title_substring],
    ):
        cp = _run(cmd)
        if cp.returncode != 0 or not (cp.stdout or "").strip():
            continue
        for line in cp.stdout.strip().splitlines():
            try:
                return int(line.strip())
            except ValueError:
                continue
    return None


def linux_window_name(wid: int) -> Optional[str]:
    """Return window title for ``wid``, or None if invalid / gone."""
    if not xdotool_available():
        return None
    cp = _run(["xdotool", "getwindowname", str(wid)])
    if cp.returncode != 0:
        return None
    name = (cp.stdout or "").strip()
    return name if name else None


def linux_window_geometry(wid: int) -> Optional[Geo]:
    """Screen (X, Y, width, height) from ``xdotool getwindowgeometry --shell``."""
    cp = _run(["xdotool", "getwindowgeometry", "--shell", str(wid)])
    if cp.returncode != 0:
        return None
    vals = {}
    for line in (cp.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    try:
        x = int(vals["X"])
        y = int(vals["Y"])
        w = int(vals["WIDTH"])
        h = int(vals["HEIGHT"])
        if w <= 0 or h <= 0:
            return None
        return x, y, w, h
    except (KeyError, ValueError):
        return None


def linux_list_visible_windows() -> List[Tuple[int, str]]:
    """Return ``(window_id, title)`` for visible X11 windows (xdotool)."""
    if not xdotool_available():
        return []
    cp = _run(["xdotool", "search", "--onlyvisible", ""])
    if cp.returncode != 0 or not (cp.stdout or "").strip():
        return []
    out: List[Tuple[int, str]] = []
    for line in cp.stdout.strip().splitlines():
        try:
            wid = int(line.strip())
        except ValueError:
            continue
        name = linux_window_name(wid) or ""
        out.append((wid, name))
    return out


def linux_activate_move_resize(wid: int, gx: int, gy: int, gwidth: int, gheight: int) -> None:
    if not xdotool_available():
        return
    subprocess.run(
        ["xdotool", "windowactivate", str(wid)],
        capture_output=True,
        timeout=8,
        check=False,
    )
    subprocess.run(
        ["xdotool", "windowmove", str(wid), str(gx), str(gy)],
        capture_output=True,
        timeout=8,
        check=False,
    )
    subprocess.run(
        ["xdotool", "windowsize", str(wid), str(gwidth), str(gheight)],
        capture_output=True,
        timeout=8,
        check=False,
    )


def linux_screen_rect_ltrb(wid: int) -> Optional[Tuple[int, int, int, int]]:
    """left, top, right, bottom in screen coordinates (for parity with GetWindowRect)."""
    g = linux_window_geometry(wid)
    if not g:
        return None
    x, y, w, h = g
    return x, y, x + w, y + h


def metrics_from_ltrb(left: int, top: int, right: int, bottom: int) -> Geo:
    """Same border heuristics as legacy win32 ``getWindow`` in core.py."""
    x = left
    y = top + 30
    w = right - x - 50
    h = bottom - y - 30
    return x, y, w, h

