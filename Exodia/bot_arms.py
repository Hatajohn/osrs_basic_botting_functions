# Importsenv
import bot_env as Env
import numpy as np
import cv2
from scipy import interpolate
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
    def click_here(self, points, center, rad=15):
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

        # Pick a point and click at
        self.click_at(point, rad=rad)


    # Move and click the mouse at a given position  
    def click_at(self, point, rad=15):
        if point == []:
            return
        
        if self._DEBUG:
            [x, y] = point
            image = Env.screen_image([0, 0, 1920, 1040])
            print('Moving mouse to: ', x, y)
            image = cv2.circle(image, (x, y), radius=rad, color=(0, 0, 255), thickness=2)
            Env.debug_view(image, title='Moving the mouse here')

        self.move_mouse(point)
        b = random.uniform(0.05, 0.09)
        time.sleep(b)
        pyautogui.click()
        b = random.uniform(0.05, 0.18)
        time.sleep(b)


    # Go through the inventory and drop all items based on points passed
    def drop_all(self, points, rect, rad=12):
        if points == []:
            return
        pyautogui.keyDown('shift')

        random.shuffle(points) # -> Need to come up with an algo for click order
        
        for p in points:
            # Adjust for global coordinates
            x = p[0] + rect[0]
            y = p[1] + rect[1]
            self.move_mouse([x, y], rad)
            b = random.uniform(0.05, 0.09)
            pyautogui.click(duration=b)
            b = random.uniform(0.05, 0.09)
            time.sleep(b)
        pyautogui.keyUp('shift')


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
    def move_mouse(self, point, rad=9):
        point = Env.pick_point_in_circle(point, rad)
        b = random.uniform(0.07, 0.284)
        # Move the mouse
        if self._DEBUG:
            debug_image = Env.screen_image([0, 0, 1920, 1040])
            debug_image = cv2.circle(debug_image, point, radius=10, color=(0,255,0), thickness=-1)
            print('XY: ', point)
            Env.debug_view(debug_image, "Center vs move point")
        
        # Get current position in order to determine how much variance to add to the ending position
        position = pyautogui.position()
        dist = math.dist(position, point)
        rad += int(dist % 5)
        print(rad)

        cp = random.randint(3, 10)  # Number of control points. Must be at least 2.
        x1, y1 = position   # Starting position
        x2, y2 = point      # Ending position

        # Distribute control points between start and destination evenly.
        x = np.linspace(x1, x2, num=cp, dtype='int')
        y = np.linspace(y1, y2, num=cp, dtype='int')

        # Randomise inner points a bit (+-RND at most).
        RND = 20
        xr = [random.randint(-RND, RND) for k in range(cp)]
        yr = [random.randint(-RND, RND) for k in range(cp)]
        xr[0] = yr[0] = xr[-1] = yr[-1] = 0
        x += xr
        y += yr

        # Approximate using Bezier spline.
        degree = 3 if cp > 3 else cp - 1  # Degree of b-spline. 3 is recommended.
                                        # Must be less than number of control points.
        tck, u = interpolate.splprep([x, y], k=degree)
        # Move upto a certain number of points
        u = np.linspace(0, 1, num=2+int(math.dist([x1,y1],[x2,y2])/50.0))
        points = interpolate.splev(u, tck)

        # Move mouse.
        duration = 0.1
        timeout = duration / len(points[0])
        point_list=zip(*(i.astype(int) for i in points))
        pick_tween = random.choice([pyautogui.easeInQuad, pyautogui.easeOutQuad, pyautogui.easeOutElastic, pyautogui.easeInBounce, pyautogui.easeInElastic])
        for point in point_list:
            #print('Moving to ', *point, ' with duration ', duration)
            pyautogui.moveTo(*point, tween=pick_tween)
            time.sleep(timeout)
        

    # Need to address this -> I personally do not drag from the center of my screen, I just full send
    def control_camera(self, center, drag_to, rad=15):
        # Move the mouse somewhere around the center of the client screen
        print('CENTER ', center)
        print('DRAG TO ', drag_to)
        # Move mouse to center of the client screen
        # move_to = pick_point_in_circle(center, rad) -> pass the point
        self.move_mouse(center)
        # Hold middle mouse and drag
        b = random.uniform(0.6, 1.0)
        drag_to = Env.pick_point_in_circle(drag_to, rad=rad)
        print('DRAGGING TO ', drag_to)
        pyautogui.dragTo(drag_to, button='middle', duration=b)


    # Pan functions take the global client center and the window dimensions of the client
    def pan_right(self, center, win_rect, y_var=0, rand=False):
        if rand:
            r = random.uniform(0.15, 0.90)
            point = [center[0] + math.floor(win_rect[2]/2 * r), center[1]]
        else:
            point = [center[0] + math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN RIGHT TO ', point)
        self.control_camera(center, point, rad=20)


    def pan_left(self, center, win_rect, y_var=0, rand=False):
        if rand:
            r = random.uniform(0.15, 0.90)
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