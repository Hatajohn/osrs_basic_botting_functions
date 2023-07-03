# This module handles actions the bot might need to perform on a regular basis

# Imports - legs do not currently perform any task in a way it could be modulated here
import bot_brain as brain
import bot_eyes as eyes
import bot_arms as arms
import random


def simple_init():
    bot_b = brain.BotBrain()
    bot_e = eyes.BotEyes()
    bot_e.setRect(bot_b.win_rect)
    bot_a = arms.BotArms()
    return [bot_b, bot_e, bot_a]


def scan_for(b_brain, b_eyes, b_arms, target, in_inventory=False, attempts = 10, DEBUG=False):
    # Target needs to be assigned
    if target is None:
        raise Exception('We cannot scan for nothing!')

    # Check each type passed to the function
    errors = []
    if (type(b_brain) is not brain):
        error = TypeError().__traceback__
        BaseException(error).add_note('Brain is the wrong type')
        errors.append(error)
    if (type(b_eyes) is not eyes):
        error = TypeError().__traceback__
        BaseException(error).add_note('Eyes is the wrong type')
        errors.append(error)
    if (type(b_arms) is not brain):
        error = TypeError().__traceback__
        BaseException(error).add_note('Arms is the wrong type')
        errors.append(error)

    # Raise all errors found, idk if this works the way I think it does
    for error in errors:
        raise error
    
    if DEBUG:
        b_eyes.force_debug(DEBUG)
    
    # All bot objects are good to go, start scanning
    click_info = b_eyes.locate_image(b_eyes.curr_client, filename=target, inv=in_inventory, name=('Scanning for %s'%(target)))

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
            
            click_info = b_eyes.locate_image(b_eyes.curr_client, filename=target, inv=in_inventory, name=('Scanning for %s'%(target)))
            attempt += 1
        # If we found the target
        if click_info != [] and attempt < attempts:
            b_arms.click_here(click_info, center=b_eyes.local_center, rect=b_brain.win_rect)

    # Go through the inventory and drop everything or drop specific items
    def clear_inventory():
        pass