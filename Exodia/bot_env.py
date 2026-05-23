from __future__ import annotations

import math
import os
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import cv2
import mss
import numpy as np
from PIL import ImageGrab

import constants

# Alias for legacy callers (`Env.PERF_TICK_S`); canonical name: `constants.OSRS_TICK_S`.
PERF_TICK_S = constants.OSRS_TICK_S

Rect = Union[List[int], Tuple[int, int, int, int]]


# ``mss`` often returns blank (all-zero) captures under **WSLg / XWayland**. Use ``wsl_ps`` when hosted
# in WSL and the desktop is rendered on Windows (interop). Regions are Win32 coordinates.
_WS_PRIMARY_CACHE: Tuple[float, Tuple[int, int, int, int]] = (0.0, (0, 0, 0, 0))
_WS_PRIMARY_CACHE_TTL_S = 4.0


def _powershell_exe() -> str:
    o = shutil.which(os.environ.get("EXODIA_POWERSHELL_EXE") or "")
    cand = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    p = Path(o).expanduser() if o else cand
    return str(p)


def _capture_backend_norm() -> str:
    raw = (os.environ.get("EXODIA_CAPTURE_BACKEND") or "mss").strip().lower()
    if raw in ("wsl_powershell", "wsl-windows", "win_gdi"):
        return "wsl_ps"
    return raw


def _posix_mnt_path_to_windows(path_posix: str) -> str:
    """POSIX path under ``/mnt/<drive>/`` to a Windows path (``C:\\...``)."""
    p = Path(path_posix).resolve().as_posix()
    if not p.startswith("/mnt/"):
        raise ValueError("wsl_ps output must resolve under /mnt/<drive>/ (got %r)" % path_posix)
    parts = [s for s in p.split("/") if s != ""]
    if len(parts) < 4 or parts[0].lower() != "mnt":
        raise ValueError("Bad POSIX path %r for wsl_ps" % path_posix)
    letter = parts[1].upper()
    rest = "\\".join(parts[2:])
    return "%s:\\%s" % (letter, rest)


def _windows_primary_bounds_wsl() -> Tuple[int, int, int, int]:
    """Cached (Left, Top, Width, Height) for Windows PrimaryScreen."""
    global _WS_PRIMARY_CACHE
    now = time.monotonic()
    stale_at, tup = _WS_PRIMARY_CACHE
    if tup[2] > 0 and (now - stale_at) < _WS_PRIMARY_CACHE_TTL_S:
        return tup
    exe = _powershell_exe()
    if not Path(exe).is_file():
        raise RuntimeError(
            "EXODIA_CAPTURE_BACKEND=wsl_ps requires %s — set EXODIA_POWERSHELL_EXE?"
            % exe,
        )
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "Write-Output ($b.Left.ToString()+','+$b.Top.ToString()+','+"
        "$b.Width.ToString()+','+$b.Height.ToString())"
    )
    r = subprocess.run(
        [exe, "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0 or not r.stdout.strip():
        stderr = (r.stderr or "").strip()
        raise RuntimeError("wsl_ps primary bounds failed (code %s): %s" % (r.returncode, stderr[:500]))
    bl, bt, bw, bh = [int(float(x.strip())) for x in r.stdout.strip().split(",", 3)]
    _WS_PRIMARY_CACHE = (now, (bl, bt, bw, bh))
    return bl, bt, bw, bh


def _grab_bgr_wsl_powershell(left: int, top: int, w: int, h: int) -> np.ndarray:
    if w <= 0 or h <= 0:
        raise ValueError("Invalid capture size %s×%s" % (w, h))
    exe = _powershell_exe()
    if not Path(exe).is_file():
        raise RuntimeError("wsl_ps: PowerShell not found at %s" % exe)
    posix_out = (
        "/mnt/c/Windows/Temp/exodia_wslps_%s_%s.png" % (os.getpid(), int(time.time() * 1000))
    )
    win_out = _posix_mnt_path_to_windows(posix_out)
    q = "'" + win_out.replace("'", "''") + "'"
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$bmp=New-Object System.Drawing.Bitmap %d,%d; "
        "$g=[System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen(%d,%d,0,0,$bmp.Size); "
        "$bmp.Save(%s,[System.Drawing.Imaging.ImageFormat]::Png); "
        "$g.Dispose(); $bmp.Dispose()"
        % (w, h, left, top, q)
    )
    r = subprocess.run(
        [exe, "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(
            "wsl_ps capture failed (code %s): %s" % (r.returncode, (r.stderr or r.stdout or "")[:500]),
        )
    try:
        img = cv2.imread(posix_out, cv2.IMREAD_COLOR)
    finally:
        try:
            os.unlink(posix_out)
        except OSError:
            pass
    if img is None or img.size == 0:
        raise RuntimeError("wsl_ps: could not read %r after capture" % posix_out)
    return img


def _grab_bgr_pil(left: int, top: int, w: int, h: int) -> np.ndarray:
    bbox = (left, top, left + w, top + h)
    shot = ImageGrab.grab(bbox=bbox)
    return cv2.cvtColor(np.asarray(shot), cv2.COLOR_RGB2BGR)


def _grab_bgr_mss(left: int, top: int, w: int, h: int) -> np.ndarray:
    with mss.mss() as sct:
        region = {"left": left, "top": top, "width": w, "height": h}
        raw = sct.grab(region)
        frame = np.asarray(raw)  # BGRA
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def _grab_bgr(left: int, top: int, w: int, h: int) -> np.ndarray:
    b = _capture_backend_norm()
    if b == "mss":
        return _grab_bgr_mss(left, top, w, h)
    if b == "wsl_ps":
        return _grab_bgr_wsl_powershell(left, top, w, h)
    return _grab_bgr_pil(left, top, w, h)


def _grab_bgr_sync(left: int, top: int, w: int, h: int) -> np.ndarray:
    """Synchronous grab for CaptureProducer (uses warm wsl_ps session when active)."""
    if _capture_backend_norm() == "wsl_ps":
        try:
            from bot_capture import get_wsl_ps_session

            return get_wsl_ps_session().grab(int(left), int(top), int(w), int(h))
        except Exception:
            return _grab_bgr_wsl_powershell(left, top, w, h)
    return _grab_bgr(left, top, w, h)


def _primary_monitor_left_top_wh() -> Tuple[int, int, int, int]:
    """Primary monitor rectangle: ``mss`` (Linux X) or Windows bounds when ``wsl_ps``."""
    if _capture_backend_norm() == "wsl_ps":
        return _windows_primary_bounds_wsl()
    with mss.mss() as sct:
        mon = sct.monitors[1]
        return int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"])


def primary_monitor_rect() -> List[int]:
    """``[left, top, width, height]`` for the primary monitor — same geometry as ``screen_image(rect=None)``."""
    l, t, w, h = _primary_monitor_left_top_wh()
    return [l, t, w, h]


def capture_backend_label() -> str:
    """Normalized ``EXODIA_CAPTURE_BACKEND`` (``mss`` | ``pil`` | ``wsl_ps``)."""
    return _capture_backend_norm()


def _input_backend_norm() -> str:
    raw = (os.environ.get("EXODIA_INPUT_BACKEND") or "").strip().lower()
    if raw in ("wsl_ps", "wsl_powershell", "wsl-windows", "win"):
        return "wsl_ps"
    if raw in ("pyautogui", "x11", ""):
        return "pyautogui"
    return raw


def input_backend_label() -> str:
    return _input_backend_norm()


def camera_rotate_mode() -> str:
    """
    How to rotate the in-game camera when panning.

    - ``keys`` (default) — Left / Right arrow keys
    - ``drag`` — middle-mouse drag (legacy)
    """
    raw = (os.environ.get("EXODIA_CAMERA_ROTATE") or "keys").strip().lower()
    if raw in ("drag", "middle", "mouse", "mmb"):
        return "drag"
    return "keys"


def camera_arrow_hold_ms(
    default_min_ms: int = 300,
    default_max_ms: int = 900,
) -> int:
    """
    Arrow-key hold duration for one camera pan (milliseconds).

    By default picks a random duration in ``[300, 900]`` ms each call.
    Set ``EXODIA_CAMERA_KEY_HOLD_MS`` for a fixed hold (disables random range).
    Override range with ``EXODIA_CAMERA_KEY_HOLD_MIN_MS`` / ``_MAX_MS``.
    Legacy ``EXODIA_CAMERA_KEY_TAPS`` multiplies the chosen value when set.
    """
    fixed = os.environ.get("EXODIA_CAMERA_KEY_HOLD_MS", "").strip()
    if fixed:
        hold_ms = max(40, int(fixed))
    else:
        lo = max(40, int(os.environ.get("EXODIA_CAMERA_KEY_HOLD_MIN_MS", str(default_min_ms))))
        hi = max(lo, int(os.environ.get("EXODIA_CAMERA_KEY_HOLD_MAX_MS", str(default_max_ms))))
        hold_ms = random.randint(lo, hi)
    taps = os.environ.get("EXODIA_CAMERA_KEY_TAPS", "").strip()
    if taps:
        hold_ms = max(40, hold_ms * max(1, int(taps)))
    return hold_ms


_VK_ARROW = {"left": 0x25, "right": 0x27}


def _wsl_run_ps(command: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet (no here-strings — safe for ``-Command``)."""
    exe = _powershell_exe()
    if not Path(exe).is_file():
        raise RuntimeError("wsl_ps input requires PowerShell at %s" % exe)
    return subprocess.run(
        [exe, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _wsl_ensure_mouse_api() -> str:
    return (
        "$m='[DllImport(\"user32.dll\")] public static extern void mouse_event(int f,int x,int y,int b,int e);'; "
        "Add-Type -MemberDefinition $m -Name ExodiaMouse -Namespace Exodia; "
    )


def _wsl_ensure_keybd_api() -> str:
    return (
        "$k='[DllImport(\"user32.dll\")] public static extern void keybd_event(byte vk,byte scan,int flags,int extra);'; "
        "Add-Type -MemberDefinition $k -Name ExodiaKey -Namespace Exodia; "
    )


def wsl_windows_set_cursor(x: int, y: int) -> None:
    """Move the Windows cursor (Win32 screen coords) from WSL via PowerShell."""
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Cursor]::Position = "
        "New-Object System.Drawing.Point(%d,%d)" % (int(x), int(y))
    )
    r = _wsl_run_ps(cmd, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps cursor move failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_cursor_position() -> Tuple[int, int]:
    """Current Windows cursor position (Win32 screen coords)."""
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$p=[System.Windows.Forms.Cursor]::Position; "
        "Write-Output ($p.X.ToString() + ',' + $p.Y.ToString())"
    )
    r = _wsl_run_ps(cmd, timeout=15)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps cursor read failed: %s" % ((r.stderr or r.stdout or "")[:300]))
    raw = (r.stdout or "").strip().split(",")
    if len(raw) != 2:
        raise RuntimeError("wsl_ps cursor read returned %r" % (r.stdout or "")[:80])
    return int(raw[0]), int(raw[1])


def _wsl_motion_timing(duration_ms: int) -> Tuple[int, int]:
    """Return ``(steps, step_sleep_ms)`` for smooth, fairly quick cursor paths."""
    duration_ms = max(100, int(duration_ms))
    steps = max(18, min(45, duration_ms // 7))
    step_ms = max(5, duration_ms // steps)
    return steps, step_ms


def wsl_move_duration_ms(
    distance_px: float,
    move_profile: str = "tight",
    hint_s: float = 0.1,
) -> int:
    """Duration for a WSL cursor move from distance (px) and profile."""
    ms = int(95 + float(distance_px) * 0.20)
    ms = max(int(max(0.08, hint_s) * 1000), ms)
    if move_profile == "open":
        ms = int(ms * 1.08)
    elif move_profile == "normal":
        ms = int(ms * 1.04)
    lo = int(os.environ.get("EXODIA_WSL_MOVE_MS_MIN", "110"))
    hi = int(os.environ.get("EXODIA_WSL_MOVE_MS_MAX", "260"))
    return max(lo, min(hi, ms))


def wsl_windows_move_to(x: int, y: int, duration_ms: int = 300) -> None:
    """Smooth move from current cursor to ``(x, y)`` in one PowerShell call."""
    steps, step_ms = _wsl_motion_timing(duration_ms)
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$p0=[System.Windows.Forms.Cursor]::Position; "
        "$p1=New-Object System.Drawing.Point(%d,%d); "
        "$n=%d; "
        "for ($i=1; $i -le $n; $i++) { "
        "  $t=$i/[double]$n; "
        "  $t=$t*$t*(3-2*$t); "
        "  $x=[int]($p0.X+($p1.X-$p0.X)*$t); "
        "  $y=[int]($p0.Y+($p1.Y-$p0.Y)*$t); "
        "  [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point($x,$y); "
        "  Start-Sleep -Milliseconds %d; "
        "}"
        % (int(x), int(y), steps, step_ms)
    )
    r = _wsl_run_ps(cmd, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps move failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_move_path(points: Sequence[Tuple[int, int]], step_ms: int = 8) -> None:
    """Step the Windows cursor through ``points`` (legacy — prefer ``wsl_windows_move_to``)."""
    delay = max(0, int(step_ms)) / 1000.0
    for x, y in points:
        wsl_windows_set_cursor(int(x), int(y))
        if delay > 0:
            time.sleep(delay)


def wsl_windows_click_current() -> None:
    """Left-click at the current Windows cursor position."""
    cmd = (
        _wsl_ensure_mouse_api()
        + "[Exodia.ExodiaMouse]::mouse_event(2,0,0,0,0); "
        "Start-Sleep -Milliseconds 30; "
        "[Exodia.ExodiaMouse]::mouse_event(4,0,0,0,0);"
    )
    r = _wsl_run_ps(cmd, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps click failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_click(x: int, y: int) -> None:
    """Left-click at Win32 screen coordinates from WSL."""
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$p=New-Object System.Drawing.Point(%d,%d); "
        "[System.Windows.Forms.Cursor]::Position=$p; "
        % (int(x), int(y))
        + _wsl_ensure_mouse_api()
        + "[Exodia.ExodiaMouse]::mouse_event(2,0,0,0,0); "
        "Start-Sleep -Milliseconds 30; "
        "[Exodia.ExodiaMouse]::mouse_event(4,0,0,0,0);"
    )
    r = _wsl_run_ps(cmd, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps click failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_left_drag_from_current(x1: int, y1: int, duration_ms: int = 350) -> None:
    """Smooth left-button drag from the **current** cursor to ``(x1, y1)``."""
    steps, step_ms = _wsl_motion_timing(duration_ms)
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        + _wsl_ensure_mouse_api()
        + "$p0=[System.Windows.Forms.Cursor]::Position; "
        "$p1=New-Object System.Drawing.Point(%d,%d); "
        "[Exodia.ExodiaMouse]::mouse_event(2,0,0,0,0); "
        "Start-Sleep -Milliseconds 100; "
        "$n=%d; "
        "for ($i=1; $i -le $n; $i++) { "
        "  $t=$i/[double]$n; "
        "  $t=$t*$t*(3-2*$t); "
        "  $x=[int]($p0.X+($p1.X-$p0.X)*$t); "
        "  $y=[int]($p0.Y+($p1.Y-$p0.Y)*$t); "
        "  [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point($x,$y); "
        "  [Exodia.ExodiaMouse]::mouse_event(1,0,0,0,0); "
        "  Start-Sleep -Milliseconds %d; "
        "} "
        "Start-Sleep -Milliseconds 40; "
        "[Exodia.ExodiaMouse]::mouse_event(4,0,0,0,0);"
        % (int(x1), int(y1), steps, step_ms)
    )
    r = _wsl_run_ps(cmd, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps left drag failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_left_drag(x0: int, y0: int, x1: int, y1: int, duration_ms: int = 350) -> None:
    """Left-button drag on Windows (inventory move, etc.)."""
    steps = max(6, min(24, duration_ms // 40))
    step_ms = max(20, duration_ms // steps)
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        + _wsl_ensure_mouse_api()
        + "$p0=New-Object System.Drawing.Point(%d,%d); "
        "$p1=New-Object System.Drawing.Point(%d,%d); "
        "[System.Windows.Forms.Cursor]::Position=$p0; "
        "[Exodia.ExodiaMouse]::mouse_event(2,0,0,0,0); "
        "Start-Sleep -Milliseconds 150; "
        "$n=%d; "
        "for ($i=1; $i -le $n; $i++) { "
        "  $t=$i/[double]$n; "
        "  $x=[int]($p0.X+($p1.X-$p0.X)*$t); "
        "  $y=[int]($p0.Y+($p1.Y-$p0.Y)*$t); "
        "  [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point($x,$y); "
        "  [Exodia.ExodiaMouse]::mouse_event(1,0,0,0,0); "
        "  Start-Sleep -Milliseconds %d; "
        "} "
        "Start-Sleep -Milliseconds 60; "
        "[Exodia.ExodiaMouse]::mouse_event(4,0,0,0,0);"
        % (int(x0), int(y0), int(x1), int(y1), steps, step_ms)
    )
    r = _wsl_run_ps(cmd, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps left drag failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_middle_drag(x0: int, y0: int, x1: int, y1: int, duration_ms: int = 600) -> None:
    """Middle-mouse drag on Windows (camera rotation in OSRS)."""
    steps = max(6, min(24, duration_ms // 40))
    step_ms = max(20, duration_ms // steps)
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        + _wsl_ensure_mouse_api()
        + "$p0=New-Object System.Drawing.Point(%d,%d); "
        "$p1=New-Object System.Drawing.Point(%d,%d); "
        "[System.Windows.Forms.Cursor]::Position=$p0; "
        "[Exodia.ExodiaMouse]::mouse_event(0x20,0,0,0,0); "
        "$n=%d; "
        "for ($i=1; $i -le $n; $i++) { "
        "  $t=$i/[double]$n; "
        "  $x=[int]($p0.X+($p1.X-$p0.X)*$t); "
        "  $y=[int]($p0.Y+($p1.Y-$p0.Y)*$t); "
        "  [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point($x,$y); "
        "  Start-Sleep -Milliseconds %d; "
        "} "
        "[Exodia.ExodiaMouse]::mouse_event(0x40,0,0,0,0);"
        % (int(x0), int(y0), int(x1), int(y1), steps, step_ms)
    )
    r = _wsl_run_ps(cmd, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps middle drag failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def wsl_windows_focus_window(title_substr: str = "RuneLite") -> bool:
    """Try to bring a Windows window to the foreground (for arrow-key camera)."""
    if not Path(_powershell_exe()).is_file():
        return False
    safe = title_substr.replace("'", "''")
    cmd = (
        "$f='[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);'; "
        "Add-Type -MemberDefinition $f -Name ExodiaFocus -Namespace Exodia; "
        "$p = Get-Process | Where-Object { $_.MainWindowTitle -like '*%s*' } | "
        "Select-Object -First 1; "
        "if ($null -eq $p) { exit 2 }; "
        "[Exodia.ExodiaFocus]::SetForegroundWindow($p.MainWindowHandle) | Out-Null"
        % safe
    )
    r = _wsl_run_ps(cmd, timeout=30)
    return r.returncode == 0


def wsl_windows_arrow_key(direction: str, hold_ms: int = 450) -> None:
    """Hold Left or Right arrow on Windows for ``hold_ms`` (``direction`` is ``left`` or ``right``)."""
    vk = _VK_ARROW.get(direction)
    if vk is None:
        raise ValueError("direction must be 'left' or 'right'")
    cmd = (
        _wsl_ensure_keybd_api()
        + "[Exodia.ExodiaKey]::keybd_event(%d,0,0,0); "
        "Start-Sleep -Milliseconds %d; "
        "[Exodia.ExodiaKey]::keybd_event(%d,0,2,0);"
        % (vk, int(hold_ms), vk)
    )
    r = _wsl_run_ps(cmd, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("wsl_ps arrow key failed: %s" % ((r.stderr or r.stdout or "")[:300]))


def send_camera_arrow(
    direction: str,
    focus_xy: Optional[Tuple[int, int]] = None,
    hold_ms: int = 450,
) -> None:
    """
    Rotate camera by holding an arrow key for ``hold_ms``.

    *focus_xy* moves the cursor over the client first; on ``wsl_ps`` also tries to
    foreground the RuneLite window.
    """
    direction = direction.lower()
    if direction not in _VK_ARROW:
        raise ValueError("direction must be 'left' or 'right'")

    title = os.environ.get("EXODIA_WINDOW_TITLE", "RuneLite")
    hold_ms = max(40, int(hold_ms))

    if _input_backend_norm() == "wsl_ps":
        wsl_windows_focus_window(title)
        if focus_xy is not None:
            wsl_windows_set_cursor(int(focus_xy[0]), int(focus_xy[1]))
            time.sleep(0.05)
        wsl_windows_arrow_key(direction, hold_ms=hold_ms)
        return

    import pyautogui

    key = "left" if direction == "left" else "right"
    if focus_xy is not None:
        pyautogui.moveTo(int(focus_xy[0]), int(focus_xy[1]), duration=0.08)
    pyautogui.keyDown(key)
    time.sleep(hold_ms / 1000.0)
    pyautogui.keyUp(key)


def human_pause(base_seconds, jitter_ratio=0.35):
    """Sleep base_seconds +/- random jitter (0 .. jitter_ratio*base). Keeps pacing less uniform."""
    if base_seconds <= 0:
        return
    span = base_seconds * jitter_ratio
    low = max(0.0, base_seconds - span)
    high = base_seconds + span
    time.sleep(random.uniform(low, high))


def screen_image(
    rect: Optional[Rect] = None, name: str = "BotEnv_Screenshot", DEBUG: bool = False
):
    """
    Capture BGR image. ``rect`` is [left, top, width, height] in **backend** screen coordinates.

    When the capture pipeline is active (``EXODIA_CAPTURE_STREAM``), returns the latest
    buffered frame without blocking on a new grab unless the buffer is stale.

    Backends (``EXODIA_CAPTURE_BACKEND``):

    - **mss** — default; X11-style. Often all-black under WSLg/XWayland.
    - **pil** — Pillow ``ImageGrab`` (may error on some Wayland stacks).
    - **wsl_ps** — Windows GDI via ``powershell.exe`` (WSL interop). Use **Win32** desktop
      coordinates; primary monitor bounds come from ``Screen.PrimaryScreen.Bounds``.

    When ``rect`` is None, geometry is the primary monitor (``mss`` monitor 1, or Windows primary
    for ``wsl_ps``).
    """
    if rect is None:
        left, top, w, h = _primary_monitor_left_top_wh()
    else:
        left, top, w, h = rect[0], rect[1], rect[2], rect[3]

    image = None
    try:
        from bot_capture import capture_stream_enabled, capture_stream_latest

        if capture_stream_enabled():
            image = capture_stream_latest(rect if rect is not None else [left, top, w, h])
    except ImportError:
        pass

    if image is None:
        image = _grab_bgr(int(left), int(top), int(w), int(h))

    if DEBUG:
        debug_view(image, title=name)

    return image


def screen_image_fast(
    rect: Rect, name: str = "BotEnv_Fast", DEBUG: bool = False
):
    """Alias for :func:`screen_image` (same backend switch); use for clarity at call sites."""
    return screen_image(rect=rect, name=name, DEBUG=DEBUG)


def screen_regions(
    regions: Iterable[Tuple[str, Rect]],
    debug: bool = False,
) -> Dict[str, np.ndarray]:
    """
    Capture multiple ROIs in one tick without duplicating full-client logic.
    ``regions`` is (label, [left, top, w, h]) screen-coordinate rectangles.
    """
    out: Dict[str, np.ndarray] = {}
    for label, rect in regions:
        r = [rect[0], rect[1], rect[2], rect[3]]
        out[label] = screen_image(rect=r, name=label if debug else "BotEnv_roi", DEBUG=debug)
    return out


def resize_image(image, scale_percent):
    width = int(image.shape[1] * scale_percent / 100)
    height = int(image.shape[0] * scale_percent / 100)
    dim = (width, height)
    return cv2.resize(image, dim, interpolation=cv2.INTER_AREA)


def block_name(image, corner=None) -> np.ndarray:
    """Draw a filled bar on ``image`` (in-place) and return **image** (``cv2.rectangle`` returns None)."""
    img = np.asarray(image, dtype=np.uint8)
    if corner is not None:
        x0, y0 = int(corner[0]), int(corner[1])
        cv2.rectangle(img, (x0, y0), (x0 + 500, y0 + 20), color=(0, 0, 0), thickness=-1)
    else:
        cv2.rectangle(img, (0, 0), (500, 25), color=(0, 0, 0), thickness=-1)
    return img


def debug_view(img, title="Debug Screenshot", scale=60):
    arr = np.asarray(img, dtype=np.uint8)
    image = arr.copy()
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)
    time.sleep(0.5)


def pick_point_in_circle(point, rad=15):
    alpha = 2 * math.pi * random.random()

    u = random.random()
    v = random.random()
    r = min(rad, abs(rad * (1 - u if u > 0.6 else 1 - v)))

    x = int(r * math.cos(alpha) + point[0])
    y = int(r * math.sin(alpha) + point[1])

    return (x, y)
