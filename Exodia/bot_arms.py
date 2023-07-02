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
    def __init__(self, DEBUG=False):
        pass

    # takes an array of points, the client center, the win_rect, then moves and clicks the mouse at about the specified point
    def click_here(self, points, center, rect, rad=15, DEBUG=False):
        _dist = sys.maxsize
        point = None
        for p in points:
            dist = math.dist(p, center)
            if DEBUG:
                print(p[0], p[1], dist)
            if dist < _dist:
                _dist = dist
                point = p
        # Pick a point inside the click area
        [x_mouse , y_mouse] = env.pick_point_in_circle(point, rad)
        x_mouse += rect[0]
        y_mouse += rect[1]

        if DEBUG:
            image = env.screen_image([0, 0, 1920, 1040])
            print('Moving mouse to: ', x_mouse, y_mouse)
            image = cv2.circle(image, (point[0] + rect[0], point[1] + rect[1]), radius=rad, color=(0, 0, 255), thickness=2)
            image = cv2.circle(image, (x_mouse, y_mouse), radius=2, color=(0, 255, 0), thickness=2)
            env.debug_view(image)

        self.move_mouse([x_mouse, y_mouse])
        b = random.uniform(0.01, 0.05)
        pyautogui.click(duration=b)

    # Should clamp n between minn and maxn
    def clamp(self, n, minn, maxn):
        return max(min(math.floor(maxn - 10), n), math.floor(minn + 10))

    def keep_point_on_screen(self, point, x, y, w, h, DEBUG=False):
        # Assume the point was generated with the image in mind, not the monitor
        # Prevent the mouse from leaving the client area
        print('CLAMP x y')
        x = self.clamp(point[0], x, x+w)
        y = self.clamp(point[1], y, y+h)
        
        if DEBUG:
            print(point[0], x, x+w)
            print(point[1], y, y+h)

        return [x, y]

    # Move mouse to a point on the screen
    def move_mouse(self, point, duration=0, DEBUG=False):
        b = random.uniform(0.07, 0.31)
        # Move the mouse
        if DEBUG:
            debug_image = env.screen_image([0, 0, 1920, 1040])
            debug_image = cv2.circle(debug_image, point, radius=10, color=(0,255,0), thickness=-1)
            print('XY: ', point)
            env.debug_view(debug_image, "Center vs move point")

        pyautogui.moveTo(point, duration=b)


    def control_camera(self, center, drag_to, rad=15, DEBUG=False):
        # Move the mouse somewhere around the center of the client screen
        print('CENTER ', center)
        print('DRAG TO ', drag_to)
        # Move mouse to center of the client screen
        # move_to = pick_point_in_circle(center, rad) -> pass the point
        self.move_mouse(center)
        # Hold middle mouse and drag
        b = random.uniform(0.6, 1.0)
        print('DRAGGING TO ', drag_to)
        pyautogui.dragTo(drag_to, button='middle', duration=b)


    def pan_right(self, center, win_rect, DEBUG=False):
        point = [center[0] + math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN RIGHT TO ', point)
        self.control_camera(point, DEBUG=DEBUG)

    def pan_left(self, center, win_rect, DEBUG=False):
        point = [center[0] - math.floor(win_rect[2]/2 * 0.90), center[1]]
        print('PAN LEFT TO ', point)
        self.control_camera(point, DEBUG=DEBUG)

    def pan_up(self, center, win_rect, DEBUG=False):
        point = [center[0], center[1] - math.floor(win_rect[3]/2 * 0.90), center[1]]
        print('PAN UP TO ', point)
        self.control_camera(point, DEBUG=DEBUG)

    def pan_down(self, center, win_rect, DEBUG=False):
        point = [center[0], center[1] + math.floor(win_rect[3]/2 * 0.90), center[1]]
        print('PAN DOWN TO ', point)
        self.control_camera(point, DEBUG=DEBUG)

    def pan_to(self, point, DEBUG=False):
        print('PAN TO ', point)
        self.control_camera(point, DEBUG=DEBUG)

    # Locates and clicks the logout button at the bottom of inv, then clicks the actual logout button
    def click_logout(self, FAST=False, DEBUG=False):
        image = screen.screen_image()
        click_info = locate_image(image, r'logout_button.png', name='Find logout button')
        # DOES NOT YET ACCOUNT FOR THE WORLD SWITCHER BEING OPEN!!!
        if not FAST:
            self.click_here(click_info, DEBUG=DEBUG)
            time.sleep(random.uniform(0.6, 1.8))
        else:
            # Hit ESC and click the logout button asap
            self.hit_escape()
            
        time.sleep(random.uniform(0.03, 0.09))
        # Small pause before grabbing a new image and clicking logout
        image = screen.screen_image()
        click_info = locate_image(image, r'logout_button2.png', name='Find logout button')
        try:
            click_here(click_info)
        except:
            print('Could not find logout button')


    def hit_escape(self):
        pyautogui.keyDown('escape')
        time.sleep(random.uniform(0.03, 0.09))
        pyautogui.keyUp('escape')