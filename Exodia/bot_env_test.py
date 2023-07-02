# Imports
import bot_env as env
import math
import cv2

#Main
if __name__ == "__main__":
    DEBUG = True
    monitor_x = 1920
    monitor_y = 1080
    dots = 10000
    center = (math.floor(monitor_x/2), math.floor(monitor_y/2))
    rad = 300

    image = env.screen_image(DEBUG=DEBUG)

    # 'max' dots in the center of the screen distributed randomly with bias
    for i in range(0, dots):
        point = env.pick_point_in_circle(center, rad=rad)
        cv2.circle(image, center, radius=rad, color=(0, 255, 0), thickness=1)
        cv2.circle(image, point, radius=1, color=(0, 0, 255), thickness=1)
    env.debug_view(image)