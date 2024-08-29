# Imports
import bot_actions as Actions
import bot_legs as Legs
import bot_eyes as Eyes
import bot_arms as Arms
import time
import random


def wait_ticks(num, adj=0):
    time.sleep(num*tick + adj + random.random()/3)


def check_color(bot_b, bot_e, bot_color):
    b = Actions.color_is_close(bot_b, bot_e, bot_color)
    if not b:
        print('UH OH')
        return False
    return True


#Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = Actions.bot_init()

    # This is a little wack. Aside from the format being BGR, I'm not sure how to get around identifying the location of the
    # highlighted agility obstacle otherwise
    purple = [255, 0, 183]
    fail_limit = 10

    tick = 0.6
    for i in range(100):
        # SEERS
        # Wall
        while True:
            Actions.click_on_color(bot_b, bot_a, bot_e, purple)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            # step 1, 12 ticks minm
            wait_ticks(9, 0.05)
            if check_color(bot_b, bot_e, (0, 0, 207)):
                break
        
        # Jump
        while True:
            Actions.click_on_color(bot_b, bot_a, bot_e, purple)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            # step 2, 12 ticks min
            wait_ticks(11, 0.05)
            if check_color(bot_b, bot_e, (122, 125, 38)):
                break
        
        # Rope
        while True:
            Actions.click_on_color(bot_b, bot_a, bot_e, purple)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            # step 3, 14 ticks min
            wait_ticks(14, 0.15)
            if check_color(bot_b, bot_e, (208, 0, 0)):
                break
        
        # Jump
        while True:
            Actions.click_on_color(bot_b, bot_a, bot_e, purple)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            # step 4, 7 ticks min
            wait_ticks(5, 0.6)
            if check_color(bot_b, bot_e, (0, 205, 205)):
                break
        
        # Jump
        while True:
            Actions.click_on_color(bot_b, bot_a, bot_e, purple)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            # step 5, 11 ticks min
            wait_ticks(9, 0.05)
            if check_color(bot_b, bot_e, (245, 245, 0)):
                break

        while True:
            Actions.click_on_color(bot_b, bot_a, bot_e, purple, range=50)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            # step 6, 6 ticks min
            wait_ticks(4, 0.3)    # teleport, 5 ticks min
            if check_color(bot_b, bot_e, (0, 105, 252)):
                break
        
        icon = r'teleport_to_camelot.png'
        while True:
            Actions.bot_update(bot_b, bot_e)
            click_info = bot_e.locate_image(filename=icon, inv=True, name='teleport to camelot')
            bot_a.click_at(click_info[0], 4)
            Actions.mouse_fidgit(bot_b, bot_a, bot_e)
            wait_ticks(3, 0.3)
            if check_color(bot_b, bot_e, (0, 255, 0)):
                break
        print('LAP DONE')
