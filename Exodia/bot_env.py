from PIL import ImageGrab
import cv2
import time
import copy
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

def debug_view(img, title="Debug Screenshot", scale=60):
    image = copy.deepcopy(img)
    image = resize_image(image, scale)
    cv2.imshow(title, np.hstack([image]))
    cv2.waitKey(0)
    # Wait for the image to close
    time.sleep(0.5)

#Main
if __name__ == "__main__":
    image = screen_image(DEBUG=True)