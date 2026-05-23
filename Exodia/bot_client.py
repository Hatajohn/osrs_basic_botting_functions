#importsEnv
import platform
import time

import bot_env as Env
import window_tool as Wt

if platform.system() == "Windows":
    import win32gui
else:
    win32gui = None  # type: ignore


class ClientWindow:
    """Find and track the RuneLite window; exposes ``win_rect`` for Eyes and capture alignment."""

    def __init__(self, DEBUG=False, window_title_substring="RuneLite"):
        self.runelite = window_title_substring
        self.id = None
        self.win_rect = []
        self._DEBUG = DEBUG
        self._geom_min_interval = float(
            __import__("os").environ.get("EXODIA_GEOM_MIN_INTERVAL", "0.15")
        )
        self._last_geom_mono = 0.0
        self._find_window(force=True)

    def update(self):
        self._find_window(force=False)
        return self.get_window_rect()

    def _find_window(self, force: bool = False):
        if platform.system() == "Windows":
            self._find_window_win32(force=force)
        else:
            self._find_window_unix(force=force)

    def _find_window_win32(self, force: bool = False):
        if (
            not force
            and self.id is not None
            and win32gui is not None
            and win32gui.IsWindow(self.id)
        ):
            now = time.monotonic()
            if now - self._last_geom_mono < self._geom_min_interval:
                return
            self._last_geom_mono = now
            self.get_window_rect()
            return
        self.id = None
        win32gui.EnumWindows(self.enum_window_callback, None)
        if self.id is not None:
            self._last_geom_mono = time.monotonic()
            self.get_window_rect()
            if self._DEBUG:
                print("Window handle: %i" % (self.id,))
                print("Window rect: ", self.win_rect)
                Env.debug_view(Env.block_name(Env.screen_image(self.win_rect)), title="Find window ID debug")
            return
        raise RuneLiteNotFoundException("RuneLite cannot be found!")

    def _find_window_unix(self, force: bool = False):
        if not Wt.xdotool_available():
            raise RuneLiteNotFoundException(
                "xdotool not found on PATH — install it (e.g. apt install xdotool) for Linux window targeting."
            )
        now = time.monotonic()
        if (
            not force
            and self.id is not None
            and (now - self._last_geom_mono) >= self._geom_min_interval
        ):
            self._last_geom_mono = now
            name = Wt.linux_window_name(int(self.id))
            if name and self.runelite in name:
                geo = Wt.linux_window_geometry(int(self.id))
                if geo:
                    x, y, w, h = geo
                    self.win_rect = [x, y, w, h]
                    return
            self.id = None

        if not force and self.id is not None and (now - self._last_geom_mono) < self._geom_min_interval:
            return

        wid = Wt.linux_search_window_id(self.runelite)
        if wid is None:
            hint = (
                "RuneLite window not found (xdotool search --name %r).\n"
                "  • Is RuneLite open and visible?\n"
                "  • On WSL: the Linux client must run under WSLg (Windows RuneLite is invisible to xdotool).\n"
                "  • List windows: python -m SacredEelFishing.sacred_eel_fishing --list-windows\n"
                "  • Manual rect: python -m SacredEelFishing.sacred_eel_fishing --rect LEFT,TOP,WIDTH,HEIGHT\n"
                "    (use capture_runelite_once.py --capture-backend wsl_ps to find coords on WSL+Windows)"
            ) % (self.runelite,)
            raise RuneLiteNotFoundException(hint)
        self.id = wid
        Wt.linux_activate_move_resize(wid, 0, 0, 865, 830)
        self._last_geom_mono = time.monotonic()
        self.get_window_rect()
        if self._DEBUG:
            print("Window id (xdotool): %i" % (wid,))
            print("Window rect: ", self.win_rect)
            Env.debug_view(Env.block_name(Env.screen_image(self.win_rect)), title="Find window ID debug")

    def enum_window_callback(self, hwnd, extra):
        if win32gui is None:
            return
        if self.runelite in win32gui.GetWindowText(hwnd) and win32gui.IsWindowVisible(hwnd):
            self.id = hwnd

    def get_window_rect(self):
        if self.id is None:
            return False
        try:
            if platform.system() == "Windows":
                rect = win32gui.GetWindowRect(self.id)
                self.win_rect = [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]
            else:
                geo = Wt.linux_window_geometry(int(self.id))
                if not geo:
                    return False
                x, y, w, h = geo
                self.win_rect = [x, y, w, h]
            if self._DEBUG:
                print("GET WINDOW RECT: ", self.win_rect)
                image = Env.screen_image(self.win_rect)
                Env.debug_view(image, title="ClientWindow Debug get_window_rect")
            return True
        except Exception:
            return False


class RuneLiteNotFoundException(Exception):
    pass


class FixedClientWindow:
    """Use a known screen rect when automatic window search fails (``--rect``)."""

    def __init__(self, win_rect: list):
        self.runelite = "fixed"
        self.id = "fixed"
        self.win_rect = [int(v) for v in win_rect]
        self._DEBUG = False

    def update(self):
        return True

    def get_window_rect(self):
        return True
