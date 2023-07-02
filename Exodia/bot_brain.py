#imports
import numpy as np
import win32gui
import cv2
import pytesseract
import pyautogui
import math
import time
import sys
import random
import copy
import bot_env as screen

# Classes -----------------------------------------------------------

# The bot brain handles knowing information pertinent to the bot functioning
# Currently it handles the window name, tesseract path, client location and id
class BotBrain():

    def __init__(self, DEBUG=False):
        self.id = -1
        self.runelite = 'RuneLite'
        # Client dimensions on the monitor
        self.win_rect = []

        # Debug flag, bot_brain(true) will show images of each step being performed
        self._DEBUG = DEBUG
        # Time period for updates, each game tick is 0.6 seconds but it probably isnt practical 
        # to try to sync the bot with the game w/o some sort of reading of the game client info
        self._t = 0.6

        # Bot needs this information before it can be ran
        self._find_window()

    
    def update(self):
        self.get_window_rect()


    def _find_window(self):  # find window name returns PID of the window, needs to be run first to establish the PID
        win32gui.EnumWindows(self.enum_window_callback, None)
        if self.id != None:
            self.get_window_rect()
            # win32gui.SetActiveWindow(winiD)
            if self._DEBUG:
                print('Window handle: %i'%(self.id))
                print('Window rect: ', self.win_rect)
                screen.debug_view(screen.screen_image(self.win_rect))
        else:
            raise RuneLiteNotFoundException('RuneLite cannot be found!')


    #Callback function for EnumWindows, once it finds the window its looking for, sets the global to the PID
    def enum_window_callback(self, hwnd, extra):
        if 'RuneLite' in win32gui.GetWindowText(hwnd) and win32gui.IsWindowVisible(hwnd):
            self.id = hwnd


    # Returns left, right, top, bottom
    def get_window_rect(self):
        rect = win32gui.GetWindowRect(self.id)
        if(self._DEBUG):
            print('GET WINDOW RECT: ', rect)
        # If the window isnt on the main monitor we need to move it so everything can work- not implemented
        self.win_rect = [rect[0], rect[1], rect[2]-rect[0], rect[3]-rect[1]]


class RuneLiteNotFoundException(Exception):
    pass


# Functions ---------------------------------------------------------

# Block the locations of the username in the client title, the chatbox, and also block the inventory from the image
def isolate_playspace(bot, image):
    # Cover the inventory
    image = cv2.rectangle(image, bot.inventory_rect, color=(0, 0, 0), thickness=-1)
    return image

# Locate the chat area on the client screen and returns the corners
def find_chat(bot, image, threshold=0.7, DEBUG=False):
    image_gray = cv2.cvtColor(screen.resize_image(image, scale_percent=70), cv2.COLOR_BGR2GRAY)
    template = cv2.imread('images/chat_template.png', 0)
    w, h = template.shape[::-1]
    pt = None
    res = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    for pt in zip(*loc[::-1]):
        rect = cv2.rectangle(image, pt, (pt[0] + w, pt[1] + h), (0, 0, 0), 2)
        cv2.circle(image, pt, radius=10, color=(255,0,0), thickness=2)
    x1, y1, x2, y2 = pt[0]+20, pt[1]+35, pt[0] + 200, pt[1] + 290
    if DEBUG:
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
    return x1, y1, x2, y2


#Main
if __name__ == "__main__":
    DEBUG = True
    bot = BotEyes(DEBUG)
    print('We are doing an action: ', get_action_text(bot, DEBUG) is 0)

    # print('Did I do it right? ', os.path.exists(tesseract_path))

    print('Get screenshot of window')
    # Some initial setup
    base_image = init_session(DEBUG=False)
    screenshot_check = screen.screen_image([0, 0, 1920, 1040])
    rect = get_window_rect(DEBUG=False)
    rect_w = get_window_rect(wrong=True)
    screenshot_check = cv2.rectangle(screenshot_check, rect, color=(0,255,0), thickness=3)
    screenshot_check = cv2.rectangle(screenshot_check, rect_w, color=(0,0,255), thickness=3)
    # debug_view(screenshot_check)
    screenshot_check = screen.screen_image(get_window_rect())
    # debug_view(screenshot_check)
    print(find_center(False))
    # cv2.imshow("First screenshot", np.hstack([image]))
    # cv2.waitKey(0)
    # find_center(image, DEBUG=True)

    # RGB color=(200,10,200) opacity 255
    # Arrays in boundaries are actually in B, G, R format

    # Colors
    # click_here([find_center()], image=copy.deepcopy(base_image))
    # time.sleep(0.6)
    # hit_escape()
    # time.sleep(0.6)
    # refresh_session()
    #click_info = locate_color(copy.deepcopy(globals()['client']), boundaries=[([216, 215, 0], [236, 235, 10])], DEBUG=True)

    # Fish
    # click_info = locate_image(image, r'Angler_Spot.png', name='Find Fishing Spots', DEBUG=True)
    # fishing_text_loc = locate_image(copy.deepcopy(base_image), r'Fishing_text.png', area='screen', name='Locate fishing text', DEBUG=DEBUG)
    # not_fishing_loc = locate_image(copy.deepcopy(base_image), r'Not_fishing_text.png', area='screen', name='Locate Not-fishing text', DEBUG=DEBUG)

    # while(not click_info):
    #    image = screen_image()
    #    # Scan for image

        # Get location for image
    DEBUG1 = False
    DEBUG2 = False
    # debug_view(base_image)
    click_info = locate_image(copy.deepcopy(base_image), r'infernal_eel_spot.png', name='Find Fishing Spots', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    print('I see %d eel spots'%(len(click_info)))
    #    attempt += 1
    #    print(attempt)
    # base_image = refresh_session()
    inv = cv2.imread('images/Session_Inventory.png')
    click_info = locate_image(copy.deepcopy(inv), r'infernal_eel_fish.png', name='Find Fish in Inv', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    if len(click_info) == 0:
        print('I have no eels')
    else:
        print('I have %d eels'%(len(click_info)))
    click_info = locate_image(copy.deepcopy(inv), r'imcando_hammer.png', name='Find Imcando Hammer in Inv', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    print('I have %d hammer'%(len(click_info)))

    print('We are doing an action: ', get_action_text() is 0)

    # Drag middle mouse from near-center to a random poing
    rand = [random.randrange(-200,200), random.randrange(-200,200)]
    # control_camera(pick_point_in_circle(rand, rad=100))

    # Find Yellow
    # click_info = locate_color(base_image, boundaries=[([0, 245, 245], [10, 255, 255])], DEBUG=True)
    # print(click_info)
    # click_here(click_info, image, DEBUG=DEBUG)
    # click_logout(DEBUG=True)
    # click_logout(FAST=True)

    click_info = locate_image(copy.deepcopy(inv), r'knife.png', name='Find Magic Trees', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    if len(click_info) == 0:
        print('I don\'t have a knife')
    else:
        print('I see %d knives'%(len(click_info)))
    click_info = locate_image(copy.deepcopy(inv), r'magic_logs.png', name='Find magic logs in inv', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    if len(click_info) == 0:
        print('I have no logs')
    else:
        print('I have %d logs'%(len(click_info)))

    if False:
        pan_left()
        time.sleep(1)
        pan_right()
        time.sleep(1)
        pan_up()
        time.sleep(1)
        pan_down()
        time.sleep(1)

        point = find_center()
        rect = get_window_rect()
        point = [point[0] - math.floor(rect[2]/2 * 0.90), point[1] - math.floor(rect[3]/2 * 0.90)]
        pan_to(point=point)
    
    # find_inventory(image, DEBUG=True)
    # find_chat(image, DEBUG=True)
    # Click on a fishing spot
            
    # image = isolate_playspace(image)
    # image = isolate_inventory(image)
    # image = resize_image(image, 75)0

    # cv2.imshow("Screenshot", np.hstack([resize_image(base_image, 50)]))
    # cv2.waitKey(0)