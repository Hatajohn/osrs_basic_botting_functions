from PIL import ImageGrab
import cv2
import time
import math
import copy
import random
import numpy as np


# Expects a tuple[x1,y1,x2,y2]
def screen_image(rect=None, isolate=False, name='BotEnv_Screenshot', DEBUG=False):
    if rect == None:
        [left, top, right, bottom] = [0, 0, 1920, 1080]
    else:
        [left, top, right, bottom] = rect
    #bbox has a different order of dimensions than GetWindowRect, right+left,etc, because right and bottom are w/h, not locations
    my_screenshot = ImageGrab.grab(bbox=(left, top, right+left, bottom+top))
    if DEBUG:
        my_screenshot.save('images/Screen_Image_Debug.png')
    image = np.array(my_screenshot.getdata(), dtype = 'uint8').reshape((my_screenshot.size[1], my_screenshot.size[0], 3))
    if DEBUG:
        debug_view(image, title='Screen_Image_Debug.png')
    # Get the image via cv2 so I don't have to worry about whatever format it wants

    # return image for cv2 -> probably want to figure out how to do this without saving the image
    return image


# Resizes a given image by a integer percentage (like 70), helpful for viewing the entirety of a screenshot
def resize_image(image, scale_percent):
    width = int(image.shape[1] * scale_percent / 100)
    height = int(image.shape[0] * scale_percent / 100)
    dim = (width, height)
    return cv2.resize(image, dim, interpolation = cv2.INTER_AREA)


# Opens a scaled-down view of a given image for debugging
def debug_view(img, title="Debug Screenshot", scale=60):
    image = copy.deepcopy(img)
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)
    # Wait for the image to close
    time.sleep(0.5)


def get_choices(rad=15, num_segs=50):
    choices = []

     # Weighted segs
    seg = float(rad)/num_segs
    _num_segs = num_segs

    # It can't be perfect
    for i in range(7, num_segs):
        # seg being 'segment radius', decrease the number of segments per group as the radius expands
        choices = choices + [i] * max(_num_segs-i, 0)
        _num_segs - 1
    return choices


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


#Main
if __name__ == "__main__":
    monitor_x = 1920
    monitor_y = 1080
    dots = 10000
    center = (math.floor(monitor_x/2), math.floor(monitor_y/2))
    rad = 300

    image = screen_image()

    # 'max' dots in the center of the screen distributed randomly with bias
    for i in range(0, dots):
        point = pick_point_in_circle(center, rad=rad)
        cv2.circle(image, center, radius=rad, color=(0, 255, 0), thickness=1)
        cv2.circle(image, point, radius=1, color=(0, 0, 255), thickness=1)
    debug_view(image)