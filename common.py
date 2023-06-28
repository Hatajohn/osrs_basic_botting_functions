#imports
import numpy as np
import win32gui
from PIL import Image, ImageGrab
import pytesseract
import pyautogui
import math
import time
import sys
import random
import cv2
import copy
import os

#Globals
# pylint: disable-next=global-statement
runelite = 'RuneLite'
winiD = -1
window_x = 1920
window_y = 1080
tesseract_path = r'..\\..\\Tesseract-OCR\\tesseract.exe'
can_see_inv = False

#Functions ---------------------------------------------------------
def find_window(DEBUG=False):  # find window name returns PID of the window, needs to be run first to establish the PID
    try:
        win32gui.EnumWindows(enum_window_callback, None)
    except Exception:
        if DEBUG:
            # print('Window enum fails after it works for some reason, I dont know what I am doing.')
            # Example on how to move and resize a window if needed, for debug it 
            win32gui.MoveWindow(winiD, 0, 0, int(window_x/2), window_y, True)
    if globals()['winiD'] != -1:
        winiD = globals()['winiD']
        # Mention the installed location of Tesseract-OCR in your system
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        # win32gui.SetActiveWindow(winiD)
        if DEBUG:
            left, top, right, bottom = get_window_rect()
            print('Window handle: %i'%(winiD))
            print('left %d top %d right %d bottom %d'%(left, top, right, bottom))
        return winiD
    else:
        return False

# Returns left, right, top, bottom
def get_window_rect():
    rect = win32gui.GetWindowRect(winiD)
    # If the window isnt on the main monitor we need to move it so everything can work
    # I'll try to work on a way to handle multiple monitors at some point :^)
    # if len(rect) == 0:
    #    win32gui.MoveWindow(winiD, 0, 0, rect[2]-rect[0], rect[3]-rect[1], True)
    return rect[0], rect[1], rect[2], rect[3]

#Callback function for EnumWindows, once it finds the window its looking for, sets the global to the PID
def enum_window_callback(hwnd, extra):
    if 'RuneLite' in win32gui.GetWindowText(hwnd) and win32gui.IsWindowVisible(hwnd):
        globals()['winiD'] = hwnd
        return False
    
def screen_image(x1=None, y1=None, x2=None, y2=None, name='screenshot.png', DEBUG=False):
    if None in [x1,x2,y1,y2]:
        left, top, right, bottom = get_window_rect()
    else:
        left, top, right, bottom = x1, y1, x2, y2
    #bbox has a different order of dimensions than GetWindowRect
    myScreenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
    myScreenshot.save('images/' + name)
    # Get the image via cv2 so I don't have to worry about whatever format it wants
    return cv2.imread('images/screenshot.png')

def get_action_text(DEBUG=False):
    scale = 300
    left, top, right, bottom = get_window_rect()
    # I don't identify the locaiton of the fishing/mining/woodcutting text, make sure it's dragged to the top,left area
    screen_image(left+30, top+50, left+130, top+70, 'Session_Action.png')
    img = resize_image(cv2.imread('images/Session_Action.png'), scale)
    if DEBUG:
        debug_view(img)

    # Need to mask for green and red 
    boundaries=[([0, 250, 0], [10, 255, 10])]
    boundaries_not=[([0, 0, 250], [10, 10, 255])]
    for (lower, upper) in boundaries:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")
        img_g = copy.deepcopy(img)
        # find the colors within the specified boundaries and apply the mask
        mask_g = cv2.inRange(img_g, lower, upper)
        output = cv2.bitwise_and(img_g, img_g, mask=mask_g)
        ret, thresh_g = cv2.threshold(mask_g, 40, 255, 0)

    for (lower, upper) in boundaries_not:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")
        img_r = copy.deepcopy(img)
        # find the colors within the specified boundaries and apply the mask
        mask_r = cv2.inRange(img_r, lower, upper)
        output = cv2.bitwise_and(img_r, img_r, mask=mask_r)
        ret, thresh_r = cv2.threshold(mask_r, 40, 255, 0)
    
    # Specify structure shape and kernel size.
    # Kernel size increases or decreases the area
    # of the rectangle to be detected.
    # A smaller value like (10, 10) will detect
    # each word instead of a sentence.
    rect_kernel_g = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    rect_kernel_r = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    
    # Applying dilation on the threshold image
    dilation_g = cv2.dilate(thresh_g, rect_kernel_g, iterations = 1)
    dilation_r = cv2.dilate(thresh_r, rect_kernel_r, iterations = 1)
    
    # Finding contours
    contours_g, hierarchy = cv2.findContours(dilation_g, cv2.RETR_EXTERNAL,
                                                    cv2.CHAIN_APPROX_NONE)
    contours_r, hierarchy = cv2.findContours(dilation_r, cv2.RETR_EXTERNAL,
                                                    cv2.CHAIN_APPROX_NONE)
    if DEBUG:
        draw_contour = cv2.drawContours(copy.deepcopy(img), contours_g, 0, color=(255,0,0), thickness=2)
        debug_view(draw_contour, "Contours Fishing")
        draw_contour = cv2.drawContours(copy.deepcopy(img), contours_r, 0, color=(255,0,0), thickness=2)
        debug_view(draw_contour, "Contours NOT Fishing")

    # Creating a copy of image
    im2 = img.copy()
    im3 = img.copy()
    
    # Looping through the identified contours
    # Then rectangular part is cropped and passed on
    # to pytesseract for extracting text from it
    working = False
    not_working = False

    for cnt in contours_g:
        x, y, w, h = cv2.boundingRect(cnt)
        # Cropping the text block for giving input to OCR
        cropped = im2[y:y + h, x:x + w]
        text = pytesseract.image_to_string(cropped)
        working = True

        if DEBUG:
            # Drawing a rectangle on copied image
            rect = cv2.rectangle(im2, (x, y), (x + w, y + h), (0, 255, 0), 2)
            print('(GREEN) WE ARE: %s'%(text))
            debug_view(rect)

    for cnt in contours_r:
        x, y, w, h = cv2.boundingRect(cnt)
        # Cropping the text block for giving input to OCR
        cropped = im3[y:y + h, x:x + w]
        text = pytesseract.image_to_string(cropped)
        not_working = True

        if DEBUG:
            # Drawing a rectangle on copied image
            rect = cv2.rectangle(im3, (x, y), (x + w, y + h), (0, 255, 0), 2)
            print('(RED) WE ARE: %s'%(text))
            debug_view(rect)

    # 2 means there is no action text, or it failed to find anything, this distinction might not be necessary
    result = 2
    if working:
        result = 0
    elif not_working:
        result = 1
    return result

# Covers username top left
def isolate_min(image):
    image = cv2.rectangle(image, pt1=(0, 0), pt2=(200, 25), color=(0, 0, 0), thickness=-1)
    return image

# Block the locations of the username in the client title, the chatbox, and also block the inventory from the image
def isolate_playspace(image):
    # print('ISOLATE PLAYSPACE')
    left, top, right, bottom = get_window_rect()
    # 0, 0, 1920, 1040
    # Rectangle points (this took me a minute because im deficient):
    #   top -> left side of screen
    #   bottom -> right side of screen
    #   right -> bottom of the screen
    #   left -> top of the screen

    # Cover the inventory
    x1 = globals()['x1']
    y1 = globals()['y1']
    x2 = globals()['x2']
    y2 = globals()['y2']
    # print(x1, y1, x2, y2)
    image = cv2.rectangle(image, (x1, y1), (x2, y2), color=(0, 0, 0), thickness=-1)
    return image

def grab_inventory(img, DEBUG=False):
    image = copy.deepcopy(img)
    try:
        [x1, y1, x2, y2] = find_inventory(image, DEBUG=DEBUG)
        left, top, right, bottom = get_window_rect()
        screen_image(x1+left, y1+top, x2+left, y2+top, 'Session_Inventory.png', DEBUG=DEBUG)

        if DEBUG:
            debug_view(image, "Session Inv")
        can_see_inv = True
        return image
    except:
        can_see_inv = False
        return False

# Locate the inventory on the client screen and returns the corners
def find_inventory(image, threshold=0.7, DEBUG=False):
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
        x1, y1, x2, y2 = pt[0]+20, pt[1]+35, pt[0] + 200, pt[1] + 293
        if DEBUG:
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
            print(x1, y1, x2, y2)
            debug_view(image_gray)
            debug_view(image)
        globals()['x1'] = x1
        globals()['y1'] = y1
        globals()['x2'] = x2
        globals()['y2'] = y2
        can_see_inv = True
        return [x1, y1, x2, y2]
    except:
        can_see_inv = False
        return []

# Locate the chat area on the client screen and returns the corners
def find_chat(image, threshold=0.7, DEBUG=False):
    image_gray = cv2.cvtColor(resize_image(image, scale_percent=70), cv2.COLOR_BGR2GRAY)
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

# Resizes a given image by a integer percentage (like 70), helpful for viewing the entirety of a screenshot
def resize_image(image, scale_percent):
    width = int(image.shape[1] * scale_percent / 100)
    height = int(image.shape[0] * scale_percent / 100)
    dim = (width, height)
    return cv2.resize(image, dim, interpolation = cv2.INTER_AREA)

def find_center(image=None, DEBUG=False):
    x1,y1,x2,y2 = get_window_rect()
    true_center = (math.floor((x2-x1)/2), math.floor((y2-y1)/2))

    if DEBUG:
        image = cv2.circle(image, (math.floor((x2-x1)/2), math.floor((y2-y1)/2)), radius=5, color=(0, 0, 255), thickness=-1)
        image = resize_image(image, 70)
        cv2.imshow("Find Center", np.hstack([image]))
        cv2.waitKey(0)

    return true_center

# takes an array of points, selects the point closest to the center of the client screen
def click_here(points, rad=15, image=None, DEBUG=False):
    #pick a point closest to the center of the screen?
    center = find_center()
    _dist = sys.maxsize
    point = None
    for p in points:
        dist = math.dist((p[0], p[1]), center)
        if DEBUG:
            print(p[0], p[1], dist)
        if dist < _dist:
            _dist = dist
            point = p
    # Pick a point inside the click area
    [x_mouse, y_mouse] = pick_point_in_circle(point[0], point[1], rad)

    if DEBUG:
        print('Moving mouse to: ', x_mouse, y_mouse)
        image = cv2.circle(image, (point[0], point[1]), radius=rad, color=(0, 0, 255), thickness=2)
        image = cv2.circle(image, (x_mouse, y_mouse), radius=2, color=(0, 255, 0), thickness=2)
        debug_view(image)

    move_mouse([x_mouse, y_mouse], rad, DEBUG=False)
    b = random.uniform(0.01, 0.05)
    pyautogui.click(duration=b)

def pick_point_in_circle(point, rad=15):
    # Pick a point inside the circle defined by the center and the radius
    x_mouse = math.floor(random.uniform(point[0]-rad, point[0]+rad))
    y_mouse = math.floor(random.uniform(point[1]-rad, point[1]+rad))
    return [x_mouse, y_mouse]

def move_mouse(point, DEBUG=False):
    x1, y1, x2, y2 = get_window_rect()
    b = random.uniform(0.07, 0.21)
    # account for the location of the top left corner since that will offset the required position
    pyautogui.moveTo(point[0] + x1, point[1] + y1, duration=b)
    b = random.uniform(0.07, 0.21)

def control_camera(drag_to, rad=40, DEBUG=False):
    # Move the mouse somewhere around the center of the client screen
    point = find_center()
    move_mouse(pick_point_in_circle(point, rad))

    # Hold middle mouse and drag
    b = random.uniform(0.1, 0.21)
    pyautogui.dragRel(drag_to, button='middle', duration=b)

# Locates and clicks the logout button at the bottom of inv, then clicks the actual logout button
def click_logout(FAST=False, DEBUG=False):
    image = screen_image()
    click_info = locate_image(image, r'logout_button.png', area=None, name='Find logout button', DEBUG=DEBUG)
    if not FAST:
        click_here(click_info, image, DEBUG=DEBUG)
        time.sleep(random.uniform(0.6, 1.8))
    else:
        # Hit ESC and click the logout button asap
        hit_escape()
        
    time.sleep(random.uniform(0.03, 0.09))
    # Small pause before grabbing a new image and clicking logout
    image = screen_image()
    click_info = locate_image(image, r'logout_button2.png', area=None, name='Find logout button', DEBUG=DEBUG)
    try:
        click_here(click_info)
    except:
        print('Could not find logout button')

def debug_view(img, title="Debug Screenshot", scale=60):
    image = copy.deepcopy(img)
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)

# Grab the first screenshot, remove the username from the top left of the client, grab the inventory position
def init_session(DEBUG=False):
    id = find_window()
    if id:
        globals()['winiD'] = id
        image = isolate_min(screen_image())
        grab_inventory(copy.deepcopy(image), DEBUG=DEBUG)
        image = isolate_playspace(image)
        return image
    else:
        return False

def refresh_session(DEBUG=False):
    if DEBUG:
        time.sleep(1)
    image = isolate_min(screen_image())
    grab_inventory(copy.deepcopy(image), DEBUG=DEBUG)
    image = isolate_playspace(image)
    return image

def hit_escape():
    pyautogui.keyDown('escape')
    time.sleep(random.uniform(0.03, 0.09))
    pyautogui.keyUp('escape')

#Main
if __name__ == "__main__":
    print('Get window dimensions and id')
    globals()['runelite'] = 'RuneLite'
    globals()['window_x'] = 1920
    globals()['window_y'] = 1040

    # print('Did I do it right? ', os.path.exists(tesseract_path))

    id = find_window()
    if id:
        print('Get screenshot of window')
        # Some initial setup
        base_image = init_session()
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
        base_image = refresh_session()
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
        control_camera(pick_point_in_circle(rand, rad=100))

        # Find Yellow
        # click_info = locate_color(base_image, boundaries=[([0, 245, 245], [10, 255, 255])], DEBUG=True)
        # print(click_info)
        # click_here(click_info, image, DEBUG=DEBUG)
        # click_logout(DEBUG=True)
        # click_logout(FAST=True)
        
        # find_inventory(image, DEBUG=True)
        # find_chat(image, DEBUG=True)
        # Click on a fishing spot
                
        # image = isolate_playspace(image)
        # image = isolate_inventory(image)
        # image = resize_image(image, 75)0

        # cv2.imshow("Screenshot", np.hstack([resize_image(base_image, 50)]))
        # cv2.waitKey(0)
    else:
        print('RuneLite not found!')