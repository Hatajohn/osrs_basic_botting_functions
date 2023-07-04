# This module handles actions the bot might need to perform on a regular basis

# Imports - legs do not currently perform any task in a way it could be modulated here
import bot_brain as Brain
import bot_eyes as Eyes
import bot_arms as Arms
import time
import random


def bot_init():
    bot_b = Brain.BotBrain()
    bot_e = Eyes.BotEyes()
    bot_e.setRect(bot_b.win_rect)
    bot_a = Arms.BotArms()
    return [bot_b, bot_e, bot_a]


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
         b_arms.click_here(click_info, center=b_eyes.local_center, rect=b_eyes.client_rect)
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
            b_arms.click_here(click_info, center=b_eyes.local_center, rect=b_eyes.client_rect)


# This will be useful for when I need to 'use' one item on another
def find_adjacent_item(b_eyes, b_arms, target_1, target_2):
    targets_1 = b_eyes.locate_image(b_eyes.curr_client, filename=target_1, inv=True, name=('Scanning for %s'%(target_1)))
    targets_2 = b_eyes.locate_image(b_eyes.curr_client, filename=target_2, inv=True, name=('Scanning for %s'%(target_2)))


#Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = bot_init()

    # scan_for(bot_e, bot_a, target=r'magic_tree_sample.png')
    bounds = [([0, 240, 240], [0, 255, 255])] # -> Yellow
    scan_for(bot_e, bot_a, method='color', bounds=bounds)

    time.sleep(5)

    # Check if the top left of the client says "Woodcutting" or whatever
    action = bot_e.get_action_text()
    print(action)
    if action != 0:
        time.sleep(2)
        scan_for(bot_e, bot_a, method='color', bounds=bounds)