# Imports
import bot_actions as Actions
import bot_legs as Legs
import bot_eyes as Eyes
import bot_arms as Arms
import time
import random


def keep_fishing(bot_e, bot_a, bot_l, state):
    action = bot_e.get_action_text()
    if action != 0:
        # Figure out why we are not fishing
        eels_inv = bot_e.locate_image(bot_e.curr_inventory, filename=r'infernal_eel_fish.png', inv=True, name='Checking inventory')
        print(len(eels_inv), state)
        if len(eels_inv) == 0:
            state = 'idle'

        if len(eels_inv) == 22:
            # Inv is full, crack the eels
            print('Crack the eels')
            Actions.use_item_on(bot_e, bot_a, r'imcando_hammer.png', r'infernal_eel_fish.png')
            state = 'cracking'
        elif len(eels_inv) > 0 and state == 'cracking':
            print('Cracking eels, %d to go!'%(len(eels_inv)))
        else:
            wait = random.randint(1,10)
            
            if wait < 9:
                print('Waiting ', wait)
                time.sleep(wait)
            else:
                wait = random.randint(15,25)
                print('WAITING LONGER: ', wait)
                time.sleep(wait)
                
            print('Looking for eels')
            Actions.scan_for(bot_e, bot_a, r'infernal_eel_spot.png', method='color', bounds=[([235, 255, 0], [250, 255, 0])])
            time.sleep(random.randrange(2,5))
        return state
    else:
        # We are fishing, keep fishing
        print('Currently fishing for eels')
        return 'fishing'

#Main
if __name__ == "__main__":
    [bot_b, bot_e, bot_a] = Actions.bot_init()
    bot_l = Legs.BotLegs(mods=[bot_b, bot_e])

    #fishing_task = bot_l.add_task(func='keep_fishing', params=[bot_e, bot_a, bot_l, 'idle'])
    #bot_l.bot_loop()

    # keep_fishing(bot_e, bot_a, bot_l, 'idle')
    timer = 6000000

    cycles = 0
    end = 0
    last_time = time.time()
    delta_time = 0
    state = 'idle'
    interval = 6000
    _interval = 6000
    # Something else needs to stop this
    while(end < timer):
        curr_time = time.time()
        # If we have passed the time period, we need to update each object legs is watching
        if delta_time > interval:
            cycles += 1
            bot_b.update()
            bot_e.update()
            state = keep_fishing(bot_e, bot_a, bot_l, state)
            last_time = time.time()
            print('Cycles: ', cycles)
        end += time.time() - last_time
        delta_time += curr_time - last_time
    