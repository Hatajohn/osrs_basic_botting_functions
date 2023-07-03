from PIL import ImageGrab
import cv2
import time
import math
import copy
import random
import numpy as np


# Expects a tuple[x1,y1,x2,y2], requires a value for cover_name if viewing an image in monitor
def screen_image(rect=None, block=False, cover_name=None, name='BotEnv_Screenshot', DEBUG=False):
    if rect == None:
        [left, top, right, bottom] = [0, 0, 1920, 1080]
    else:
        [left, top, right, bottom] = rect

    #bbox has a different order of dimensions than GetWindowRect, right+left,etc, because right and bottom are w/h, not locations
    my_screenshot = ImageGrab.grab(bbox=(left, top, right+left, bottom+top))
    if DEBUG:
        my_screenshot.save('images/Screen_Image_Debug.png')

    # Convert to a format cv2 can use
    image = cv2.cvtColor(np.asarray(my_screenshot), cv2.COLOR_RGB2BGR)

    # Cover the client name if given the top left corner- the first two indices of rect
    if block:
        if cover_name != []:
            image = block_name(image, cover_name)
        else:
            image = block_name(image)

        if DEBUG:
            debug_view(image, title='Post client name block')
    # Get the image via cv2 so I don't have to worry about whatever format it wants

    # return image for cv2 -> probably want to figure out how to do this without saving the image
    return image    


# Resizes a given image by a integer percentage (like 70), helpful for viewing the entirety of a screenshot
def resize_image(image, scale_percent):
    width = int(image.shape[1] * scale_percent / 100)
    height = int(image.shape[0] * scale_percent / 100)
    dim = (width, height)
    return cv2.resize(image, dim, interpolation = cv2.INTER_AREA)


# Given the client image, covers the client name
def block_name(image, corner=None):
    if corner != None:
        return cv2.rectangle(image, [corner[0], corner[1], 500, 20], color=(0, 0, 0), thickness=-1)
    return cv2.rectangle(image, [0, 0, 500, 25], color=(0, 0, 0), thickness=-1)


# Opens a scaled-down view of a given image for debugging
def debug_view(img, title="Debug Screenshot", scale=60):
    image = copy.deepcopy(img)
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)
    # Wait for the image to close
    time.sleep(0.5)


# Divides a circle into tiered areas-> visualize an archery target
# Most of the points should fall towards the center
def pick_point_in_circle(point, rad=15):
    # Pick a point inside the circle defined by the center and the radius
    # random angle
    alpha = 2 * math.pi * random.random()

    # random radius
    u = random.random()
    v = random.random()
    r = min(rad, abs(rad * (1 - u if u > 0.6 else 1 - v)))

    # calculating coordinates
    x = int(r * math.cos(alpha) + point[0])
    y = int(r * math.sin(alpha) + point[1])

    return (x, y)