# Imports
import bot_env as env
import cv2
import pyautogui
import time
import math
import random
import sys


# This file is for the mouse movements and actions required for the bot to interact with the client
class BotArms():


    # Constructor
    def __init__(self, DEBUG=False):
        self._DEBUG=DEBUG
        pass


    # takes an array of points, the client center, the win_rect, then moves and clicks the mouse at about the specified point
    def click_here(self, points, center, rect, rad=15):
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
        # Pick a point inside the click area
        x = point[0] + rect[0]
        y = point[1] + rect[1]

        if self._DEBUG:
            image = env.screen_image([0, 0, 1920, 1040])
            print('Moving mouse to: ', x, y)
            image = cv2.circle(image, (x, y), radius=rad, color=(0, 0, 255), thickness=2)
            env.debug_view(image, title='Moving the mouse here')

        self.move_mouse([x, y])
        b = random.uniform(0.05, 0.09)
        pyautogui.click(duration=b)
        b = random.uniform(0.05, 0.09)
        time.sleep(b)


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


    # Move mouse to a point on the screen
    def move_mouse(self, point, rad=11, duration=0):
        b = random.uniform(0.07, 0.284)
        # Move the mouse
        if self._DEBUG:
            debug_image = env.screen_image([0, 0, 1920, 1040])
            debug_image = cv2.circle(debug_image, point, radius=10, color=(0,255,0), thickness=-1)
            print('XY: ', point)
            env.debug_view(debug_image, "Center vs move point")
        position = pyautogui.position()
        dist = math.dist(position, point)
        rad += int(dist % 5)
        print(rad)
        point = env.pick_point_in_circle(point, rad)
        pyautogui.moveTo(point, duration=b)


    def control_camera(self, center, drag_to, rad=15):
        # Move the mouse somewhere around the center of the client screen
        print('CENTER ', center)
        print('DRAG TO ', drag_to)
        # Move mouse to center of the client screen
        # move_to = pick_point_in_circle(center, rad) -> pass the point
        self.move_mouse(center)
        # Hold middle mouse and drag
        b = random.uniform(0.6, 1.0)
        drag_to = env.pick_point_in_circle(drag_to)
        print('DRAGGING TO ', drag_to, rad=rad)
        pyautogui.dragTo(drag_to, button='middle', duration=b)


    # Pan functions take the global client center and the window dimensions of the client
    def pan_right(self, center, win_rect, rand=False):
        if rand:
            r = random.randrange(0.15, 0.90)
            point = [center[0] + math.floor(win_rect[2]/2 * r), center[1]]
        else:
            point = [center[0] + math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN RIGHT TO ', point)
        self.control_camera(center, point, rad=20)


    def pan_left(self, center, win_rect, rand=False):
        if rand:
            r = random.randrange(0.15, 0.90)
            point = [center[0] - math.floor(win_rect[2]/2 * r), center[1]]
        else:
            point = [center[0] - math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN LEFT TO ', point)
        self.control_camera(center, point, rad=20)


    def pan_up(self, center, win_rect):
        point = [center[0], center[1] - math.floor(win_rect[3]/2 * 0.90), center[1]]
        print('PAN UP TO ', point)
        self.control_camera(center, point)


    def pan_down(self, center, win_rect):
        point = [center[0], center[1] + math.floor(win_rect[3]/2 * 0.90), center[1]]
        print('PAN DOWN TO ', point)
        self.control_camera(center, point)


    def pan_to(self, point, center):
        print('PAN TO ', point)
        self.control_camera(center, point)


    # THIS DOES NOT WORK
    def hit_escape(self):
        pyautogui.keyDown('escape')
        time.sleep(random.uniform(0.03, 0.09))
        pyautogui.keyUp('escape')