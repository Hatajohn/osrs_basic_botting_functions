import bot_eyes as Eyes
import bot_env as Env
import bot_actions as Actions
import cv2
import copy

# MAKE SURE launch.json HAS 'justmycode' DISABLED

# Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = Actions.bot_init(False)

    bot_e.force_debug(True)

    cyan = [([180, 180, 0], [255, 255, 40])]
    yellow = [([0, 230, 230], [30, 255, 255])]
    purple = [([240, 0, 160], [255, 0, 200])]

    # Color order is BGR for some reason
    # point = bot_e.locate_color(bot_e.curr_client, boundaries=cyan, multi=True)
    point = bot_e.locate_cluster(bot_e.curr_client, boundaries=purple, draw_contours=False, draw_clusters=False, draw_lines=True)
    temp_client = copy.deepcopy(bot_e.curr_client)
    temp_client = cv2.circle(temp_client, point[0], 10, color=(0, 0, 255), thickness=3)
    Env.debug_view(temp_client)

    # IMPLEMENT sklearn.cluster.DBSCAN IN ORDER TO HANDLE POORLY DEFINED COMPLEX SHAPES VIA CONTOURS
    # I NEED DENSITY-BASED CLUSTERING