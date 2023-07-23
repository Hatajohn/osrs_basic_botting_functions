# Imports
import bot_actions as Actions
import bot_legs as Legs
import bot_eyes as Eyes
import bot_arms as Arms
import time
import random

def wait_ticks(num, adj=0):
    time.sleep(num*tick + adj)

#Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = Actions.bot_init()

    # This is a little wack. Aside from the format being BGR, I'm not sure how to get around identifying the location of the
    # highlighted agility obstacle otherwise
    purple = [255, 0, 183]

    tick = 0.6

    # SEERS
    # Wall
    Actions.click_on_color(bot_a, bot_e, purple)
    # step 1, 12 ticks minm
    wait_ticks(10)
    # Jump
    Actions.click_on_color(bot_a, bot_e, purple)
    # step 2, 12 ticks min
    wait_ticks(11)
    # Rope
    Actions.click_on_color(bot_a, bot_e, purple)
    # step 3, 14 ticks min
    wait_ticks(15)
    # Jump
    Actions.click_on_color(bot_a, bot_e, purple)
    # step 4, 7 ticks min
    wait_ticks(7, 0.1)
    # Jump
    Actions.click_on_color(bot_a, bot_e, purple)
    # step 5, 11 ticks min
    wait_ticks(9, 0.3)
    Actions.click_on_color(bot_a, bot_e, purple)
    # step 6, 6 ticks min
    wait_ticks(6, 0.1)    # teleport, 5 ticks min
    icon = r'teleport_to_camelot.png'
    # bot_e.force_debug(True)
    click_info = bot_e.locate_image(bot_e.curr_inventory, filename=icon, inv=True, name='teleport to camelot')
    bot_a.click_at(click_info[0])
    wait_ticks(5)
    print('LAP DONE')
