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
class bot_brain():

    def __init__(self, DEBUG=False):
        self.id = -1
        self.runelite = 'RuneLite'
        self.tesseract_path = r'..\\..\\Tesseract-OCR\\tesseract.exe'
        # Client dimensions on the monitor
        self.win_rect = []
        # Inventory location in a client screenshot
        self.inventory_rect = []
        # Inventory location on monitor
        self.inventory_global = []
        # Center of the client
        self.local_center = []
        self.global_center = []

        # Debug flag, bot_brain(true) will show images of each step being performed
        self._DEBUG = DEBUG
        # Time period for updates, each game tick is 0.6 seconds but it probably isnt practical 
        # to try to sync the bot with the game w/o some sort of reading of the game client info
        self._t = 0.6

        # Bot needs this information before it can be ran
        self._find_window()
        self.image = screen.screen_image(self.win_rect)
        self.grab_inventory(copy.deepcopy(self.image))
        self.find_center()

    
    def update(self):
        self.get_window_rect()
        self.image = screen.screen_image(self.win_rect)
        self.grab_inventory(copy.deepcopy(self.image))
        self.find_center()


    def _find_window(self):  # find window name returns PID of the window, needs to be run first to establish the PID
        win32gui.EnumWindows(self.enum_window_callback, None)
        if self.id != None:
            self.get_window_rect()
            # Mention the installed location of Tesseract-OCR in your system
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
            # win32gui.SetActiveWindow(winiD)
            if self._DEBUG:
                print('Window handle: %i'%(self.id))
                print('Window rect: ', self.win_rect)
                debug_view(screen.screen_image(self.win_rect))
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


    def grab_inventory(self, img):
        image = copy.deepcopy(img)
        try:
            self.find_inventory(image)
            # Need to account for the fact that the image typically sent to grab_inventory is of the client only
            if self._DEBUG:
                debug_view(image, "Session Inventory")
                screenshot_check = screen.screen_image()
                screenshot_check = cv2.rectangle(screenshot_check, self.inventory_global, color=(0,255,0), thickness=2)
                debug_view(screenshot_check, title='True inventory position')
        except:
            return False


    # Locate the inventory on the client screen and returns the corners
    def find_inventory(self, image, threshold=0.7):
        image_gray = cv2.cvtColor(copy.deepcopy(image), cv2.COLOR_BGR2GRAY)
        template = cv2.imread('images/ui_icons.png', 0)
        w, h = template.shape[::-1]
        pt = None
        res = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)

        loc = np.where(res >= threshold)
        # print('LOC: ', len(loc))
        for pt in zip(*loc[::-1]):
            cv2.rectangle(image_gray, pt, (pt[0] + w, pt[1] + h), (0, 0, 255), 2)
            # cv2.circle(image, pt, radius=10, color=(255,0,0), thickness=2)
        try:
            #182x255
            self.inventory_rect = [pt[0]+20, pt[1]+35, 182, 255]
            self.inventory_global = [self.inventory_rect[0] + self.win_rect[0], self.inventory_rect[1] + self.win_rect[1], self.inventory_rect[2], self.inventory_rect[3]]
            if self._DEBUG:
                cv2.rectangle(image, self.inventory_rect, (0, 0, 255), 2)
                print(self.inventory_rect)
                debug_view(image_gray)
                debug_view(image)
        except:
            return []
        
    # A function that sets the local and global centers. This can be used in other functions since the character is always semi-centered
    def find_center(self):
        #win_rect is top-left (x, y) then width and height
        image_center = [math.floor(self.win_rect[2]/2), math.floor(self.win_rect[3]/2)]
        true_center = [image_center[0] + self.win_rect[0], image_center[1] + self.win_rect[1]]

        if self._DEBUG:
            print('IMAGE CENTER ', image_center)
            print('TRUE CENTER ', true_center)
            image = screen.screen_image(self.win_rect)
            image = cv2.circle(image, center=image_center, radius=10, color=(255, 100, 100), thickness=-1)
            debug_view(image, title='IMAGE CENTER')
            image = screen.screen_image([0, 0, 1920, 1040])
            image = cv2.circle(image, center=true_center, radius=10, color=(100, 100, 255), thickness=-1)
            debug_view(image, title='TRUE CENTER')

        self.local_center = image_center
        self.global_center = true_center

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

def locate_color(image, boundaries=[([180, 0, 180], [220, 20, 220])], DEBUG=False):
    #Remove the username from the window, the chatbox, and the inventory from the image
    image = isolate_playspace(image)

    # define the list of boundaries
    # loop over the boundaries
    for (lower, upper) in boundaries:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")

        # find the colors within the specified boundaries and apply the mask
        mask = cv2.inRange(image, lower, upper)
        output = cv2.bitwise_and(image, image, mask=mask)
        ret, thresh = cv2.threshold(mask, 40, 255, 0)
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    if DEBUG:
            cv2.imwrite("images/Locate_Image_DebugPRE.png", image)

    if len(contours) != 0:
        # find the biggest countour by the area -> usually implies the closest contour to the camera
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)

        # The biggest contour will be drawn with a green outline
        image = cv2.rectangle(image, pt1=(x, y), pt2=(x+w, y+h), color=(0, 255, 0), thickness=2)
        image = cv2.drawContours(image, contours, 0, color=(0,255,0), thickness=2)
        mask = np.zeros(image.shape[:2], np.uint8)
        for cont in contours:
            x_c, y_c, w_c, h_c = cv2.boundingRect(cont)
            if mask[y_c + int(round(h_c/2)), x_c + int(round(w_c/2))] != 255:
                mask[y_c:y_c+h_c,x_c:x_c+w_c] = 255
                if(x != x_c or y != y_c or w != w_c or h != h_c):
                    # Other contours will be highlighted with the opposite color of upper for visibility
                    image = cv2.rectangle(image, pt1=(x_c, y_c), pt2=(x_c+w_c, y_c+h_c), color=(0,0,255), thickness=2)
        # Center of the contour
        x_center, y_center = (math.floor(x+w/2), math.floor(y+h/2))
        click_radius = math.floor(min(w, h)/2)

        if DEBUG:
            cv2.imwrite("images/Locate_Image_DebugPOST.png", image)
            print('Length of contours: %d'%(len(contours)))
            print(x, y, w, h)

        return [x_center, y_center]
    else:
        return []
    
def locate_image(img_rgb, filename, threshold=0.7, name='Screenshot', DEBUG_1=False, DEBUG_2=False):
    try:
        img_gray = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)
        template = cv2.imread('images/' + filename, 0)
        w, h = template.shape[::-1]
        pt = None
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        items = []
        # Add a mask to remove duplicate matches
        mask = np.zeros(img_rgb.shape[:2], np.uint8)
        for pt in zip(*loc[::-1]):
            # Add a circle to mark a match
            if DEBUG_2:
                cv2.rectangle(img_rgb, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), thickness=1)
            if mask[pt[1] + int(round(h/2)), pt[0] + int(round(w/2))] != 255:
                mask[pt[1]:pt[1]+h, pt[0]:pt[0]+w] = 255
                # An array of points
                items.append([pt[0]+math.floor(w/2), pt[1]+math.floor(h/2)])
                if DEBUG_1:
                    cv2.circle(img_rgb, (pt[0]+math.floor(w/2), pt[1]+math.floor(h/2)), radius=min(math.floor(w/3), math.floor(h/3)), color=(0,255,0), thickness=1)
        if DEBUG_2:
            cv2.imshow(name, np.hstack([img_rgb]))
            cv2.waitKey(0)
            time.sleep(0.5)
        if len(items) > 0:
            return items
        print('Locate image could not find the image')
        return []
    except:
        print('Locate image failed!')
        return []

# takes an array of points, the client center, the win_rect, then moves and clicks the mouse at about the specified point
def click_here(points, center, rect, rad=15, DEBUG=False):
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
    [x_mouse , y_mouse] = pick_point_in_circle(point, rad)
    x_mouse += rect[0]
    y_mouse += rect[1]

    if DEBUG:
        image = screen.screen_image([0, 0, 1920, 1040])
        print('Moving mouse to: ', x_mouse, y_mouse)
        image = cv2.circle(image, (point[0] + rect[0], point[1] + rect[1]), radius=rad, color=(0, 0, 255), thickness=2)
        image = cv2.circle(image, (x_mouse, y_mouse), radius=2, color=(0, 255, 0), thickness=2)
        debug_view(image)

    move_mouse([x_mouse, y_mouse])
    b = random.uniform(0.01, 0.05)
    pyautogui.click(duration=b)

# Should clamp n between minn and maxn
def clamp(n, minn, maxn):
    return max(min(math.floor(maxn - 10), n), math.floor(minn + 10))

def pick_point_in_circle(point, rad=15):
    # Pick a point inside the circle defined by the center and the radius
    x_mouse = math.floor(random.uniform(point[0]-rad, point[0]+rad))
    y_mouse = math.floor(random.uniform(point[1]-rad, point[1]+rad))
    return [x_mouse, y_mouse]

def keep_point_on_screen(point):
    x1, y1, x2, y2 = get_window_rect()
    # Assume the point was generated with the image in mind, not the monitor
    # Prevent the mouse from leaving the client area
    print('CLAMP x y')
    x = clamp(point[0], x1, x2)
    y = clamp(point[1], y1, y2)
    print(x, x1, x2)
    print(y, y1, y2)
    return [x, y]

# Move mouse to a point on the screen
def move_mouse(point, duration=0, DEBUG=False):
    b = random.uniform(0.07, 0.31)
    # Move the mouse
    if DEBUG:
        debug_image = screen.screen_image([0, 0, 1920, 1040])
        debug_image = cv2.circle(debug_image, point, radius=10, color=(0,255,0), thickness=-1)
        print('XY: ', point)
        debug_view(debug_image, "Center vs move point")

    pyautogui.moveTo(point, duration=b)

def control_camera(drag_to, rad=15, DEBUG=False):
    # Move the mouse somewhere around the center of the client screen
    center = find_center()
    print('CENTER ', center)
    print('DRAG TO ', drag_to)
    # Move mouse to center of the client screen
    move_to = pick_point_in_circle(center, rad)
    print('MOVING MOUSE TO CENTER ', move_to)
    move_mouse(center)
    # Hold middle mouse and drag
    b = random.uniform(0.6, 1.0)
    print('DRAGGING TO ', drag_to)
    pyautogui.dragTo(drag_to, button='middle', duration=b)


def pan_right(DEBUG=False):
    point = find_center()
    rect = get_window_rect()
    point = [point[0] + math.floor(rect[2]/2 * 0.90), point[1]]
    print('PAN RIGHT TO ', point)
    control_camera(point, DEBUG=DEBUG)

def pan_left(DEBUG=False):
    point = find_center()
    rect = get_window_rect()
    point = [point[0] - math.floor(rect[2]/2 * 0.90), point[1]]
    print('PAN LEFT TO ', point)
    control_camera(point, DEBUG=DEBUG)

def pan_up(DEBUG=False):
    point = find_center()
    rect = get_window_rect()
    point = [point[0], point[1] + math.floor(rect[3]/2 * 0.90)]
    print('PAN LEFT TO ', point)
    control_camera(point, DEBUG=DEBUG)

def pan_down(DEBUG=False):
    point = find_center()
    rect = get_window_rect()
    point = [point[0], point[1] - math.floor(rect[3]/2 * 0.90)]
    print('PAN LEFT TO ', point)
    control_camera(point, DEBUG=DEBUG)

def pan_to(point, DEBUG=False):
    print('PAN TO ', point)
    control_camera(point, DEBUG=DEBUG)

# Locates and clicks the logout button at the bottom of inv, then clicks the actual logout button
def click_logout(FAST=False, DEBUG=False):
    image = screen.screen_image()
    click_info = locate_image(image, r'logout_button.png', name='Find logout button')
    # DOES NOT YET ACCOUNT FOR THE WORLD SWITCHER BEING OPEN!!!
    if not FAST:
        click_here(click_info, DEBUG=DEBUG)
        time.sleep(random.uniform(0.6, 1.8))
    else:
        # Hit ESC and click the logout button asap
        hit_escape()
        
    time.sleep(random.uniform(0.03, 0.09))
    # Small pause before grabbing a new image and clicking logout
    image = screen.screen_image()
    click_info = locate_image(image, r'logout_button2.png', name='Find logout button')
    try:
        click_here(click_info)
    except:
        print('Could not find logout button')

def debug_view(img, title="Debug Screenshot", scale=60):
    image = copy.deepcopy(img)
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)
    # Wait for the image to close
    time.sleep(0.5)

# Grab the first screenshot, remove the username from the top left of the client, grab the inventory position
def init_session(DEBUG=False):
    id = find_window()
    if id:
        image = isolate_min(screen.screen_image())
        if DEBUG:
            debug_view(image)
        grab_inventory(copy.deepcopy(image), DEBUG=DEBUG)
        image = isolate_playspace(image)
        return image
    else:
        return False

def refresh_session(DEBUG=False):
    if DEBUG:
        time.sleep(1)
    image = isolate_min(screen.screen_image())
    grab_inventory(copy.deepcopy(image), DEBUG=DEBUG)
    image = isolate_playspace(image)
    return image

def hit_escape():
    pyautogui.keyDown('escape')
    time.sleep(random.uniform(0.03, 0.09))
    pyautogui.keyUp('escape')

#Main
if __name__ == "__main__":
    DEBUG = True
    bot = bot_brain(DEBUG)
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