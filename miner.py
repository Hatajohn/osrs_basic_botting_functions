from core import findWindow_runelite

from functions import Image_count
from functions import image_Rec_clicker
from functions import random_breaks
from functions import screen_Image
from functions import release_drop_item
from functions import drop_item
from functions import Image_to_Text
from PIL import Image

import numpy as np
import cv2
import time
import random
import pyautogui

global hwnd
global iflag
global icoord
iflag = False
global newTime_break
newTime_break = False
global timer
global timer_break
global ibreak

def timer():
    startTime = time.time()
    return startTime

def random_pause():
    b = random.uniform(20, 250)
    print('pausing for ' + str(b) + ' seconds')
    time.sleep(b)
    newTime_break = True


def random_inventory():
    global newTime_break
    print('inventory tab')
    b = random.uniform(1.5, 15)
    pyautogui.press('f4')
    time.sleep(b)
    pyautogui.press('f4')
    b = random.uniform(1.5, 2)
    time.sleep(b)
    pyautogui.press('esc')
    newTime_break = True


def random_combat():
    global newTime_break
    print('combat tab')
    b = random.uniform(1.5, 15)
    pyautogui.press('f1')
    time.sleep(b)
    pyautogui.press('f1')
    b = random.uniform(1.5, 2)
    time.sleep(b)
    pyautogui.press('esc')
    newTime_break = True


def random_skills():
    global newTime_break
    print('skills tab')
    b = random.uniform(1.5, 15)
    pyautogui.press('f2')
    time.sleep(b)
    pyautogui.press('f2')
    b = random.uniform(1.5, 2)
    time.sleep(b)
    pyautogui.press('esc')
    newTime_break = True


def random_quests():
    global newTime_break
    print('quest tab')
    b = random.uniform(1.5, 15)
    pyautogui.press('f3')
    time.sleep(b)
    pyautogui.press('f3')
    b = random.uniform(1.5, 2)
    time.sleep(b)
    pyautogui.press('esc')
    newTime_break = True


options = {0: random_inventory,
           1: random_combat,
           2: random_skills,
           3: random_quests,
           4: random_pause}


def random_break(start, c):
    global newTime_break
    startTime = time.time()
    # 1200 = 20 minutes
    a = random.randrange(0, 4)
    if startTime - start > c:
        options[a]()
        newTime_break = True


def randomizer(timer_breaks, ibreaks):
    global newTime_break
    global timer_break
    global ibreak
    random_break(timer_breaks, ibreaks)
    if newTime_break == True:
        timer_break = timer()
        ibreak = random.randrange(600, 2000)
        newTime_break = False

    # b = random.uniform(4, 5)


def Miner_Image():
    screen_Image(150, 150, 600, 750, 'miner_img.png')

def drop_ore():
    print("dropping ore starting...")
    invent_crop()
    drop_item()
    image_Rec_clicker(r'copper_ore.png', 'dropping item', 5, 5, 0.9, 'left', 20, 0, 0)
    image_Rec_clicker(r'clay_ore.png', 'dropping item', 5, 5, 0.9, 'left', 20, 0, 0)
    image_Rec_clicker(r'coal_ore.png', 'dropping item', 5, 5, 0.9, 'left', 20,  0, 0)
    image_Rec_clicker(r'iron_ore.png', 'dropping item', 5, 5, 0.9, 'left', 20, 0, 0)
    image_Rec_clicker(r'tin_ore.png', 'dropping item', 5, 5, 0.9, 'left', 20,  0, 0)
    release_drop_item()
    print("dropping ore done")


def findarea_single(ore, cropx, cropy):
    Miner_Image()
    image = cv2.imread(r"miner_img.png")

    # B, G, R
#--------------------- ADD OBJECTS -------------------
    tin = ([103, 86, 65], [145, 133, 128])
    copper = ([35, 70, 120], [65, 110, 170])
    coal = ([20, 30, 30], [30, 50, 50])
    iron = ([15, 20, 40], [25, 40, 70])
    iron2 = ([17, 20, 42], [25, 38, 70])
    clay = ([50, 105, 145], [60, 125, 165])
    red = ([0, 0, 180], [80, 80, 255])
    green = ([0, 180, 0], [80, 255, 80])
    amber = ([0, 160, 160], [80, 255, 255])
    # --------------------- ADD OBJECTS -------------------
    ore_list = [tin, copper, coal, iron, iron2, clay, red, green, amber]
    boundaries = [ore_list[ore]]
    # loop over the boundaries
    for (lower, upper) in boundaries:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")
        # find the colors within the specified boundaries and apply
        # the mask
        mask = cv2.inRange(image, lower, upper)
        output = cv2.bitwise_and(image, image, mask=mask)
        ret, thresh = cv2.threshold(mask, 40, 255, 0)
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if len(contours) != 0:
        # find the biggest countour (c) by the area
        c = max(contours, key=cv2.contourArea)

        x, y, w, h = cv2.boundingRect(c)
        x = random.randrange(x + 5, x + max(w - 5, 6)) + cropx  # 950,960
        print('x: ', x)
        y = random.randrange(y + 5, y + max(h - 5, 6)) + cropy # 490,500
        print('y: ', y)
        b = random.uniform(0.1, 0.3)
        pyautogui.moveTo(x, y, duration=b)
        b = random.uniform(0.07, 0.11)
        pyautogui.click(duration=b)


def invent_crop():
    return screen_Image(620, 480, 820, 750, 'inventshot.png')
def count_gems():
    return Image_count('gem_icon.png')

def count_geo():
    return Image_count('geo_icon.png')

def count_gems2():
    return Image_count('gem_icon2.png')

def inv_count(name):
    return Image_count(name + '_ore.png') + Image_count('gold_ore.png')



def resizeImage():
    screen_Image(40, 51, 105, 71, 'screen_resize.png')
    png = 'screen_resize.png'
    im = Image.open(png)
    # saves new cropped image
    width, height = im.size
    new_size = (width * 4, height * 4)
    im1 = im.resize(new_size)
    im1.save('textshot.png')


def powerminer_text(ore,manual,num):
    powerlist = ['tin', 'copper', 'coal', 'iron', 'iron', 'clay', 'red', 'green', 'amber']
    print(powerlist[ore])
    j = 0
    while j < 10:
        randomizer(timer_break, ibreak)
        r = random.uniform(0.1, 5)
        inventory = int(inv_count(powerlist[ore])) + int(count_gems()) + int(count_gems2()) + int(count_geo())
        print('ore: ', int(inventory), "| gems: ", int(count_gems() + count_gems2()), "| clues: ", int(count_geo()))
        if inventory > 27:
            drop_ore()
            random_breaks(0.2, 0.7)
        resizeImage()
        mined_text = Image_to_Text('thresh', 'textshot.png')
        if mined_text.lower() != 'mining':
            random_breaks(0.05, 0.1)
            if manual:
                findarea_single(num, 150, 150)
            else:
                findarea_single(ore, 150, 150)
            random_breaks(0.5, 1)




resizeImage()
x = random.randrange(100, 250)
y = random.randrange(400, 500)
pyautogui.click(x, y, button='right')
ibreak = random.randrange(300, 2000)
print('will break in   ' + str(ibreak / 60) + ' minutes')
timer_break = timer()
powerminer_text(1, True, 7) #copper amd #green border