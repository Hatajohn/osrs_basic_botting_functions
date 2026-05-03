import os
import platform
import sys
import yaml

_EXODIA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exodia")
if _EXODIA not in sys.path:
    sys.path.insert(0, _EXODIA)

import window_tool as wt  # noqa: E402

global hwnd
hwnd = 0

with open("pybot-config.yaml", "r") as yamlfile:
    data = yaml.load(yamlfile, Loader=yaml.FullLoader)

if platform.system() == "Windows":
    import win32gui  # noqa: E402
else:
    win32gui = None  # type: ignore


def findWindow(data):
    global hwnd
    if platform.system() == "Windows":
        hwnd = win32gui.FindWindow(None, data)
        win32gui.SetActiveWindow(hwnd)
        win32gui.MoveWindow(hwnd, 0, 0, 865, 830, True)
    else:
        wid = wt.linux_search_window_id(data)
        if wid is None:
            raise RuntimeError("Window not found via xdotool: %r" % (data,))
        hwnd = wid
        wt.linux_activate_move_resize(wid, 0, 0, 865, 830)


def getWindow(data):
    global hwnd
    if platform.system() == "Windows":
        hwnd = win32gui.FindWindow(None, data)
        win32gui.SetActiveWindow(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
    else:
        wid = wt.linux_search_window_id(data)
        if wid is None:
            raise RuntimeError("Window not found via xdotool: %r" % (data,))
        hwnd = wid
        ltrb = wt.linux_screen_rect_ltrb(wid)
        if not ltrb:
            raise RuntimeError("xdotool geometry failed for window %s" % wid)
        rect = ltrb  # left, top, right, bottom
    x = rect[0]
    y = rect[1] + 30
    w = rect[2] - x - 50
    h = rect[3] - y - 30
    return x, y, w, h


def findWindow_runelite():
    findWindow("RuneLite")


def findWindow_openosrs():
    findWindow("OpenOSRS")


print("Operating system:", platform.system())
_title = data[0]["Config"]["client_title"]
findWindow(_title)
