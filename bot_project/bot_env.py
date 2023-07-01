from PIL import Image, ImageGrab
import cv2

# Expects a tuple[x1,y1,x2,y2]
def screen_image(rect=None, isolate=False, name='screenshot.png'):
    if rect == None:
        [left, top, right, bottom] = [0, 0, 1920, 1080]
    else:
        [left, top, right, bottom] = rect
    #bbox has a different order of dimensions than GetWindowRect, right+left,etc, because right and bottom are w/h, not locations
    my_screenshot = ImageGrab.grab(bbox=(left, top, right+left, bottom+top))
    my_screenshot.save('images/' + name)
    # Get the image via cv2 so I don't have to worry about whatever format it wants
    return cv2.imread('images/screenshot.png')