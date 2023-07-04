# This module handles actions the bot might need to perform on a regular basis

# Imports - legs do not currently perform any task in a way it could be modulated here
import bot_brain as Brain
import bot_eyes as Eyes
import bot_arms as Arms
import random


def simple_init():
    bot_b = Brain.BotBrain()
    bot_e = Eyes.BotEyes()
    bot_e.setRect(bot_b.win_rect)
    bot_a = Arms.BotArms()
    return [bot_b, bot_e, bot_a]


def scan_for(b_brain, b_eyes, b_arms, target, attempts = 10, DEBUG=False):
    # Target needs to be assigned
    if target is None:
        raise Exception('We cannot scan for nothing!')

    # Check each type passed to the function -> probably dont need this?
    if type(b_brain) is not Brain:
        error = TypeError().__traceback__
        BaseException(error).add_note('Brain is the wrong type')
        raise error
    if type(b_eyes) is not Eyes:
        error = TypeError().__traceback__
        BaseException(error).add_note('Eyes is the wrong type')
        raise error
    if type(b_arms) is not Brain:
        error = TypeError().__traceback__
        BaseException(error).add_note('Arms is the wrong type')
        raise error
    
    if DEBUG:
        b_eyes.force_debug(DEBUG)
    
    # All bot objects are good to go, start scanning
    click_info = b_eyes.locate_image(b_eyes.curr_client, filename=target, name=('Scanning for %s'%(target)))

    # Image was found, Bob's your uncle
    if click_info != []:
         b_arms.click_here(click_info, center=b_eyes.local_center, rect=b_brain.win_rect)
    else:
        # We did not find the object for one reason or another, try looking around? Give it 10 attemps
        attempt = 0
        while click_info == [] and attempt < attempts:
            r = random.random()
            if r > 0.5:
                b_arms.pan_right(center=b_eyes.global_center, win_rect=b_eyes.client_rect, rand=True)
            else:
                b_arms.pan_left(center=b_eyes.global_center, win_rect=b_eyes.client_rect, rand=True)
            
            click_info = b_eyes.locate_image(b_eyes.curr_client, filename=target, name=('Scanning for %s'%(target)))
            attempt += 1
        # If we found the target
        if click_info != [] and attempt < attempts:
            print('I found the target')
            b_arms.click_here(click_info, center=b_eyes.local_center, rect=b_brain.win_rect)


# This will be useful for when I need to 'use' one item on another
def find_adjacent_item(b_eyes, b_arms, target_1, target_2):
    targets_1 = b_eyes.locate_image(b_eyes.curr_client, filename=target_1, inv=True, name=('Scanning for %s'%(target_1)))
    targets_2 = b_eyes.locate_image(b_eyes.curr_client, filename=target_2, inv=True, name=('Scanning for %s'%(target_2)))


#Main
if __name__ == "__main__":
    [bot_b, bot_e, bot_a] = simple_init()