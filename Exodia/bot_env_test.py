# Imports
import bot_env as Env
import math
import random
import cv2


#Main
if __name__ == "__main__":
    DEBUG = True
    monitor_x = 1920
    monitor_y = 1080
    dots = 30
    center = (math.floor(monitor_x/2), math.floor(monitor_y/2))
    rad = 11

    image = Env.screen_image(DEBUG=DEBUG)
    cv2.circle(image, center, radius=rad, color=(0, 255, 0), thickness=1)
    # 'max' dots in the center of the screen distributed randomly with bias
    for i in range(0, dots):
        point = Env.pick_point_in_circle(center, rad=11)
        c = (int(255*random.random()), int(255*random.random()), int(255*random.random()))
        cv2.circle(image, point, radius=1, color=c, thickness=1)
    Env.debug_view(image)