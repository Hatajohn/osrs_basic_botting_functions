# This module handles actions the bot might need to perform on a regular basis

# Imports - legs do not currently perform any task in a way it could be modulated here
import bot_brain as Brain
import bot_eyes as Eyes
import bot_arms as Arms
import bot_env as Env
import math
import time
import random


# Initialize the necessary objects
def bot_init(DEBUG=False):
    bot_b = Brain.BotBrain()
    bot_e = Eyes.BotEyes(DEBUG=DEBUG)
    bot_e.setRect(bot_b.win_rect)
    bot_a = Arms.BotArms()
    return [bot_b, bot_e, bot_a]


# Update the client and inventory images
def bot_update(bot_b, bot_e):
    bot_b.update()
    bot_e.setRect(bot_b.win_rect)


# Look for either an image or a colorband in the playspace
def scan_for(b_eyes, b_arms, target='', method='image', bounds=[], attempts = 10, DEBUG=False):
    # Target needs to be assigned
    if target is None:
        raise Exception('We cannot scan for nothing!')
    
    if DEBUG:
        b_eyes.force_debug(DEBUG)
    
    # All bot objects are good to go, start scanning
    if method == 'image':
        click_info = b_eyes.locate_image(b_eyes.curr_client, filename=target, name=('Scanning for %s'%(target)))
    elif method == 'color':
        click_info = b_eyes.locate_color(b_eyes.curr_client, boundaries=bounds)

    # Image was found, Bob's your uncle
    if click_info != []:
        b_arms.click_here(click_info, center=b_eyes.local_center)
    else:
        # We did not find the object for one reason or another, try looking around? Give it 10 attemps
        attempt = 0
        while click_info == [] and attempt < attempts:
            r = random.random()
            if r > 0.5:
                b_arms.pan_right(center=b_eyes.global_center, win_rect=b_eyes.client_rect, rand=True)
            else:
                b_arms.pan_left(center=b_eyes.global_center, win_rect=b_eyes.client_rect, rand=True)
            
            b_eyes.update()

            if method == 'image':
                click_info = b_eyes.locate_image(b_eyes.curr_client, filename=target, name=('Scanning for %s'%(target)))
            elif method == 'color':
                click_info = b_eyes.locate_color(b_eyes.curr_client, boundaries=bounds)
            attempt += 1

        # If we found the target
        if click_info != [] and attempt < attempts:
            print('I found the target')
            b_arms.click_here(click_info, center=b_eyes.local_center)


# This will be useful for when I need to 'use' one item on another in my inv, like for making potions
# Both target params are singular image files, target_2 can end up being multiple items, but only one will be clicked
def use_item_on(b_eyes, b_arms, target_1, target_2):
    targets_1 = b_eyes.locate_image(filename=target_1, inv=True, name=('Scanning for %s'%(target_1)))
    targets_2 = b_eyes.locate_image(filename=target_2, inv=True, name=('Scanning for %s'%(target_2)))
    # Assuming the first target_1 is valid
    b_arms.click_here(targets_2, targets_1[0], rad=11)
    b_arms.click_at(targets_1[0], rad=11)

# Attempts to locate and click on an image within an image
def click_on_image(bot_brain, bot_arms, bot_eyes, target, refresh=True):
    if refresh:
        bot_update(bot_brain, bot_eyes)
    target = bot_eyes.locate_image(filename=target, inv=False)
    target = random.choice(target)
    bot_arms.click_at(target)

# Attempts to click on a color on the screen closest to the center of the image, if provided a target will try to click on the color near the target
def click_on_color(bot_brain, bot_arms, bot_eyes, color, shade=20, range=20, use_target=False, c_target=(0,0)):
    bot_update(bot_brain, bot_eyes)
    # min 0
    [b, g, r] = color
    color_lower = [max(b-shade, 0), max(g-shade, 0), max(r-shade, 0)]
    # max 255
    color_upper = [min(b+shade, 255), min(g+shade, 255), min(r+shade, 255)]

    # print(color_lower)
    # print(color_upper)
    # purple = [([240, 0, 160], [255, 0, 200])]
    point = bot_eyes.locate_cluster(boundaries=[(color_lower, color_upper)], cluster_dist=range, use_target=use_target, c_target=c_target)
    # locate cluster will return the point closest to the center of the client
    bot_arms.click_at(point, 9)
    # bot_arms.move_mouse(point)

# Runs the above function with enabled target params
def click_color_near_color(bot_brain, bot_arms, bot_eyes, color, target_color, shade=20, range=20):
    click_on_color(bot_brain, bot_arms, bot_eyes, color, shade=20, range=20, use_target=True, c_target=bot_eyes.locate_color(target_color))

# Checks if a color is near a target point
def color_is_close(bot_brain, bot_eyes, color, shade=10, dist=40, range=300):
    bot_update(bot_brain, bot_eyes)
    # min 0
    [b, g, r] = color
    color_lower = [max(b-shade, 0), max(g-shade, 0), max(r-shade, 0)]
    # max 255
    color_upper = [min(b+shade, 255), min(g+shade, 255), min(r+shade, 255)]

    print(color_lower)
    print(color_upper)
    point = bot_eyes.locate_cluster(boundaries=[(color_lower, color_upper)], cluster_dist=range)
    if len(point) == 2 and math.dist(bot_eyes.global_center, point) < range:
        return True
    return False

# Basically the function above
def check_color(bot_b, bot_e, bot_color):
    b = color_is_close(bot_b, bot_e, bot_color)
    if not b:
        print('UH OH')
        return False
    return True

# moves mouse with additional radius
def mouse_fidgit(bot_brain, bot_arms, bot_eyes, rad=200):
    #484x338
    bot_update(bot_brain, bot_eyes)
    goto = [bot_eyes.global_center[0] + 484,  bot_eyes.global_center[1] + 338]
    bot_arms.move_mouse(goto, rad=rad)


#Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = bot_init()

    # Env.debug_view(bot_e.curr_client, "Initial")

    # scan_for(bot_e, bot_a, target=r'magic_tree_sample.png')
    # bounds = [([0, 240, 240], [0, 255, 255])] # -> Yellow
    # scan_for(bot_e, bot_a, method='color', bounds=bounds)
    

    purple = [255, 0, 183]
    yellow = [0, 255, 255]
    cyan = [255, 255, 0]
    # bot_a.force_debug(True)
    #click_on_color(bot_a, bot_e, cyan)
    # bot_e.force_debug(True)
    for i in range(0, 15):
        click_on_color(bot_b, bot_a, bot_e, purple)
        mouse_fidgit(bot_b, bot_a, bot_e, rad=500)
        time.sleep(0.1)
    #click_on_color(bot_a, bot_e, yellow)

    # time.sleep(5)

    # Check if the top left of the client says "Woodcutting" or whatever
    # action = bot_e.get_action_text()
    # print(action)
    # if action != 0:
        # time.sleep(2)
        # scan_for(bot_e, bot_a, method='color', bounds=bounds)

    # Example for 'use_item_on'
    # use_item_on(bot_e, bot_a, r'knife.png', r'magic_logs.png')
    # use_item_on(bot_e, bot_a, r'magic_logs.png', r'knife.png')