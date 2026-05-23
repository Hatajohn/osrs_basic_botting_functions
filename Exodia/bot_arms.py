# Imports
import os
import bot_env as Env
import numpy as np
import cv2
from scipy import interpolate
import pyautogui
import time
import math
import random
import sys
from typing import Sequence

# Mild tweens only (no elastic/bounce — they overshoot and risk dense-UI misclicks).
_TWEENS_TIGHT = (
    pyautogui.easeInOutQuad,
    pyautogui.easeInQuad,
    pyautogui.easeOutQuad,
)
_TWEENS_NORMAL = _TWEENS_TIGHT + (pyautogui.easeInCubic, pyautogui.easeOutCubic)
_SAFE_EXTRA = getattr(pyautogui, "easeInOutCubic", pyautogui.easeInOutQuad)
_TWEENS_OPEN = _TWEENS_NORMAL + (_SAFE_EXTRA,)


def _bezier_rnd_max(rad: int, dist: float, move_profile: str) -> int:
    if move_profile == "tight":
        return min(20, max(2, rad // 2))
    if move_profile == "open":
        return min(40, max(6, rad + int(dist % 10)))
    return min(20, max(3, (rad * 2) // 3 + int(dist % 7)))


def _tween_pool(move_profile: str):
    if move_profile == "tight":
        return _TWEENS_TIGHT
    if move_profile == "open":
        return _TWEENS_OPEN
    return _TWEENS_NORMAL


# This file is for the mouse movements and actions required for the bot to interact with the client
class BotArms():


    # Constructor
    def __init__(self, DEBUG=False):
        self._DEBUG=DEBUG
        # Any duration less than this is rounded to 0.0 to instantly move the mouse.
        pyautogui.MINIMUM_DURATION = 0  # Default: 0.1
        # Minimal number of seconds to sleep between mouse moves.
        pyautogui.MINIMUM_SLEEP = 0  # Default: 0.05
        # The number of seconds to pause after EVERY public function call.
        pyautogui.PAUSE = 0  # Default: 0.1

    def force_debug(self, debug):
        self._DEBUG = debug


    # takes an array of points, a center point used to find the closest distance, 
    # the win_rect, and then moves and clicks the mouse at about the specified point
    def click_here(self, points, center, rad=15, move_profile="tight"):
        if points == []:
            return
        _dist = sys.maxsize
        point = None
        for p in points:
            dist = math.dist(p, center)
            if self._DEBUG:
                print(p[0], p[1], dist)
            if dist < _dist:
                _dist = dist
                point = p

        self.click_at(point, rad=rad, move_profile=move_profile)


    # Move and click the mouse at a given position  
    def click_at(self, point, rad=15, duration=0.1, move_profile="tight"):
        if point is None or point == []:
            return
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return

        target = Env.pick_point_in_circle([int(point[0]), int(point[1])], rad)

        if self._DEBUG:
            x, y = target
            image = Env.screen_image([0, 0, 1920, 1040])
            print('Moving mouse to: ', x, y)
            image = cv2.circle(image, (x, y), radius=rad, color=(0, 0, 255), thickness=2)
            Env.debug_view(image, title='Moving the mouse here')

        if Env.input_backend_label() == "wsl_ps":
            self.move_mouse(target, rad=0, duration=max(0.12, duration), move_profile=move_profile)
            b = random.uniform(0.03, 0.05)
            time.sleep(b)
            Env.wsl_windows_click_current()
            b = random.uniform(0.04, 0.06)
            time.sleep(b)
            return

        self.move_mouse(target, rad=0, duration=duration, move_profile=move_profile)
        b = random.uniform(0.03, 0.05)
        time.sleep(b)
        pyautogui.click()
        b = random.uniform(0.04, 0.06)
        time.sleep(b)


    def drag_at(
        self,
        start: Sequence[int],
        end: Sequence[int],
        *,
        rad: int = 8,
        duration: float = 0.35,
        move_profile: str = "tight",
    ) -> None:
        """Left-click drag from ``start`` to ``end`` (Win32 screen coordinates)."""
        if start is None or end is None:
            return
        if len(start) < 2 or len(end) < 2:
            return

        start_pt = Env.pick_point_in_circle([int(start[0]), int(start[1])], rad)
        end_pt = Env.pick_point_in_circle([int(end[0]), int(end[1])], rad)

        if self._DEBUG:
            image = Env.screen_image([0, 0, 1920, 1040])
            cv2.circle(image, start_pt, rad, (0, 0, 255), 2)
            cv2.circle(image, end_pt, rad, (0, 255, 0), 2)
            cv2.arrowedLine(image, start_pt, end_pt, (255, 255, 0), 2)
            Env.debug_view(image, title="drag_at")

        if Env.input_backend_label() == "wsl_ps":
            b = random.uniform(0.03, 0.05)
            time.sleep(b)
            self.move_mouse(start_pt, rad=0, duration=0.10, move_profile=move_profile)
            time.sleep(random.uniform(0.03, 0.05))
            drag_dist = math.dist(start_pt, end_pt)
            drag_ms = Env.wsl_move_duration_ms(drag_dist, move_profile, duration)
            drag_ms = max(140, min(280, drag_ms))
            Env.wsl_windows_left_drag_from_current(
                end_pt[0],
                end_pt[1],
                duration_ms=drag_ms,
            )
            time.sleep(random.uniform(0.06, 0.10))
            return

        self.move_mouse(start_pt, rad=0, duration=0.08, move_profile=move_profile)
        time.sleep(random.uniform(0.04, 0.07))
        pyautogui.mouseDown(button="left")
        time.sleep(random.uniform(0.05, 0.09))
        pyautogui.dragTo(
            end_pt[0],
            end_pt[1],
            button="left",
            duration=max(0.15, duration),
            _pause=False,
        )
        pyautogui.mouseUp(button="left")
        time.sleep(random.uniform(0.06, 0.10))


    # Go through the inventory and drop all items based on points passed
    def drop_all(self, points, rect, rad=12):
        if points == []:
            return
        pyautogui.keyDown("shift")
        try:
            random.shuffle(points)  # -> Need to come up with an algo for click order

            for p in points:
                x = p[0] + rect[0]
                y = p[1] + rect[1]
                self.move_mouse([x, y], rad=rad, move_profile="tight")
                b = random.uniform(0.05, 0.09)
                pyautogui.click(duration=b)
                b = random.uniform(0.05, 0.09)
                time.sleep(b)
        finally:
            pyautogui.keyUp("shift")


    # Should clamp n between minn and maxn
    def clamp(self, n, minn, maxn):
        return max(min(math.floor(maxn - 10), n), math.floor(minn + 10))


    def keep_point_on_screen(self, point, x, y, w, h):
        # Assume the point was generated with the image in mind, not the monitor
        # Prevent the mouse from leaving the client area
        print('CLAMP x y')
        x = self.clamp(point[0], x, x+w)
        y = self.clamp(point[1], y, y+h)
        
        if self._DEBUG:
            print(point[0], x, x+w)
            print(point[1], y, y+h)

        return [x, y]


    # Move mouse to a point on the screen using Bezier curves
    # move_profile: "tight" (default, dense UI), "normal", "open" (sparse / camera drags)
    def move_mouse(self, point, rad=9, duration=0.1, move_profile="tight"):
        point = Env.pick_point_in_circle(point, rad)
        if self._DEBUG:
            debug_image = Env.screen_image([0, 0, 1920, 1040])
            debug_image = cv2.circle(debug_image, point, radius=10, color=(0,255,0), thickness=-1)
            print('XY: ', point)
            Env.debug_view(debug_image, "Center vs move point")

        if Env.input_backend_label() == "wsl_ps":
            try:
                x1, y1 = Env.wsl_windows_cursor_position()
                dist = math.dist((x1, y1), point)
            except RuntimeError:
                dist = 300.0
            ms = Env.wsl_move_duration_ms(dist, move_profile, duration)
            Env.wsl_windows_move_to(int(point[0]), int(point[1]), duration_ms=ms)
            return

        position = pyautogui.position()
        dist = math.dist(position, point)
        rad_eff = rad + int(dist % 5)

        cp = random.randint(3, 10)
        x1, y1 = position
        x2, y2 = point

        x = np.linspace(x1, x2, num=cp, dtype='int')
        y = np.linspace(y1, y2, num=cp, dtype='int')

        RND = _bezier_rnd_max(rad_eff, dist, move_profile)
        xr = [random.randint(-RND, RND) for k in range(cp)]
        yr = [random.randint(-RND, RND) for k in range(cp)]
        xr[0] = yr[0] = xr[-1] = yr[-1] = 0
        x += xr
        y += yr

        list_length = 0
        pick_tween = None
        try:
            degree = 3 if cp > 3 else cp - 1
            tck, u = interpolate.splprep([x, y], k=degree)
            u = np.linspace(0, 1, num=2+int(math.dist([x1,y1],[x2,y2])/50.0))
            points = interpolate.splev(u, tck)
            list_length = len(points[0])

            point_list = zip(*(i.astype(int) for i in points))
            pick_tween = random.choice(_tween_pool(move_profile))
        except Exception:
            print('Move_to errored, sending to destination')
            point_list = [point]
            list_length = 1
            pick_tween = None

        timeout = duration / max(list_length, 1)
        for pt in point_list:
            pyautogui.moveTo(*pt, tween=pick_tween)
            time.sleep(timeout)
        

    # Need to address this -> I personally do not drag from the center of my screen, I just full send
    def control_camera(self, center, drag_to, rad=15):
        # Move the mouse somewhere around the center of the client screen
        print('CENTER ', center)
        print('DRAG TO ', drag_to)
        b = random.uniform(0.6, 1.0)
        start = Env.pick_point_in_circle(center, rad)
        end = Env.pick_point_in_circle(drag_to, rad=rad)
        print('DRAGGING TO ', end)

        if Env.input_backend_label() == "wsl_ps":
            Env.wsl_windows_middle_drag(
                start[0], start[1], end[0], end[1], duration_ms=int(b * 1000)
            )
            return

        self.move_mouse(start, move_profile="open")
        pyautogui.dragTo(end[0], end[1], button='middle', duration=b)


    def _camera_key_rotate(self, direction: str, center) -> None:
        """Rotate camera by holding an arrow key (OSRS default when not using middle-mouse drag)."""
        focus = Env.pick_point_in_circle(center, rad=12)
        hold_ms = Env.camera_arrow_hold_ms()
        print("CAMERA %s (arrow hold %dms)" % (direction.upper(), hold_ms))
        Env.send_camera_arrow(direction, focus_xy=(focus[0], focus[1]), hold_ms=hold_ms)
        time.sleep(random.uniform(0.12, 0.22))

    # Pan functions take the global client center and the window dimensions of the client
    def pan_right(self, center, win_rect, y_var=0, rand=False):
        if Env.camera_rotate_mode() == "keys":
            self._camera_key_rotate("right", center)
            return
        if rand:
            r = random.uniform(0.15, 0.90)
            point = [center[0] + math.floor(win_rect[2]/2 * r), center[1]]
        else:
            point = [center[0] + math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN RIGHT TO ', point)
        self.control_camera(center, point, rad=20)


    def pan_left(self, center, win_rect, y_var=0, rand=False):
        if Env.camera_rotate_mode() == "keys":
            self._camera_key_rotate("left", center)
            return
        if rand:
            r = random.uniform(0.15, 0.90)
            point = [center[0] - math.floor(win_rect[2]/2 * r), center[1]]
        else:
            point = [center[0] - math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN LEFT TO ', point)
        self.control_camera(center, point, rad=20)


    def pan_up(self, center, win_rect):
        point = [center[0], center[1] - math.floor(win_rect[3] / 2 * 0.90)]
        print('PAN UP TO ', point)
        self.control_camera(center, point)


    def pan_down(self, center, win_rect):
        point = [center[0], center[1] + math.floor(win_rect[3] / 2 * 0.90)]
        print('PAN DOWN TO ', point)
        self.control_camera(center, point)


    def pan_to(self, point, center):
        print('PAN TO ', point)
        self.control_camera(center, point)

    def walk_direction(
        self,
        center,
        win_rect,
        direction: str,
        *,
        distance_frac: float = 0.32,
        click_rad: int = 8,
    ) -> list:
        """
        Click the ground to walk the character (minimap/main view click).

        ``center`` / ``win_rect`` match ``pan_left`` / ``pan_right`` (screen center + client size).
        """
        from bot_search import ground_click_target

        if center is None or win_rect is None or len(win_rect) < 4:
            return []
        client_rect = [int(win_rect[i]) for i in range(4)]
        target = ground_click_target(client_rect, center, direction, distance_frac=distance_frac)
        print("WALK %s -> click ground %s" % (direction.upper(), target))
        self.click_at(target, rad=click_rad, move_profile="open")
        return target


    # THIS DOES NOT WORK
    def hit_escape(self):
        pyautogui.keyDown('escape')
        time.sleep(random.uniform(0.03, 0.09))
        pyautogui.keyUp('escape')