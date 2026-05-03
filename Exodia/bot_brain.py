#importsEnv
import platform
import bot_env as Env
import window_tool as Wt

if platform.system() == "Windows":
    import win32gui
else:
    win32gui = None  # type: ignore


# The bot brain handles knowing information pertinent to the bot functioning
# Currently it handles finding RuneLite's PID, tesseract path, client location/dimensions
class BotBrain:

    def __init__(self, DEBUG=False, window_title_substring="RuneLite"):
        self.runelite = window_title_substring
        # Native window id: HWND on Windows, xdotool window id on Linux
        self.id = None
        # Client dimensions on the monitor: [left, top, width, height]
        self.win_rect = []

        self._DEBUG = DEBUG
        self._find_window()

    def update(self):
        self._find_window()
        return self.get_window_rect()

    def _find_window(self):
        if platform.system() == "Windows":
            self._find_window_win32()
        else:
            self._find_window_unix()

    def _find_window_win32(self):
        self.id = None
        win32gui.EnumWindows(self.enum_window_callback, None)
        if self.id is not None:
            self.get_window_rect()
            if self._DEBUG:
                print("Window handle: %i" % (self.id,))
                print("Window rect: ", self.win_rect)
                Env.debug_view(Env.block_name(Env.screen_image(self.win_rect)), title="Find window ID debug")
            return True
        raise RuneLiteNotFoundException("RuneLite cannot be found!")

    def _find_window_unix(self):
        if not Wt.xdotool_available():
            raise RuneLiteNotFoundException(
                "xdotool not found on PATH — install it (e.g. apt install xdotool) for Linux window targeting."
            )
        wid = Wt.linux_search_window_id(self.runelite)
        if wid is None:
            raise RuneLiteNotFoundException(
                "RuneLite window not found (xdotool search --name %r)." % (self.runelite,)
            )
        self.id = wid
        Wt.linux_activate_move_resize(wid, 0, 0, 865, 830)
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
                # Match Windows path: outer window rect for screenshots
                self.win_rect = [x, y, w, h]
            if self._DEBUG:
                print("GET WINDOW RECT: ", self.win_rect)
                image = Env.screen_image(self.win_rect)
                Env.debug_view(image, title="BotBrain Debug get_window_rect")
            return True
        except Exception:
            return False


class RuneLiteNotFoundException(Exception):
    pass
