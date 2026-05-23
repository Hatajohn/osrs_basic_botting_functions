# Imports
import bot_actions as Actions
import bot_legs as Legs
import bot_eyes as Eyes
import bot_arms as Arms
import time
import random


def keep_fishing(client, bot_e, bot_a, bot_l, state):
    action = bot_e.get_action_text()
    if action != 0:
        # Figure out why we are not fishing
        eels_inv = bot_e.locate_image(filename=r'infernal_eel_fish.png', inv=True, name='Checking inventory')
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
            # Actions.scan_for(bot_e, bot_a, r'infernal_eel_spot.png', method='color', bounds=[([235, 255, 0], [250, 255, 0])])
            Actions.click_on_color(client, bot_a, bot_e, color=(255, 255 ,0), range=20)
            time.sleep(random.randrange(2,5))
        return state
    else:
        # We are fishing, keep fishing
        print('Currently fishing for eels')
        return 'fishing'

#Main
if __name__ == "__main__":
    [client, bot_e, bot_a] = Actions.bot_init()
    bot_l = Legs.BotLegs(mods=[client, bot_e])
    # bot_e.force_debug(True)

    # fishing_task = bot_l.add_task(func='keep_fishing', params=[client, bot_e, bot_a, bot_l, 'idle'])
    # bot_l.bot_loop()

    # keep_fishing(client, bot_e, bot_a, bot_l, 'idle')
    # Session wall-clock cap (legacy literal treated as milliseconds).
    timer_session_ms = 6000000
    deadline = time.monotonic() + timer_session_ms / 1000.0
    interval_s = 6.0

    cycles = 0
    cracking = False
    next_cycle = time.monotonic()

    while time.monotonic() < deadline:
        now = time.monotonic()
        if now < next_cycle:
            time.sleep(min(0.005, next_cycle - now))
            continue
        next_cycle += interval_s

        cycles += 1
        Actions.bot_update(client, bot_e)
        action_code = bot_e.get_action_text()
        eels_inv = bot_e.locate_image(
            filename=r"infernal_eel_fish.png", inv=True, name="Checking inventory"
        )
        if len(eels_inv) == 0 and cracking:
            cracking = False
        if action_code != 0 and not cracking and len(eels_inv) < 22:
            Actions.click_on_image(client, bot_a, bot_e, target=r"infernal_eel_fish.png")
            time.sleep(3)
        elif len(eels_inv) == 22 or cracking:
            print("START CRACKING")
            cracking = True
            Actions.use_item_on(bot_e, bot_a, r"imcando_hammer.png", r"infernal_eel_fish.png")
            eels_inv = bot_e.locate_image(
                filename=r"infernal_eel_fish.png", inv=True, name="Checking inventory"
            )
            print(len(eels_inv))
        print("Cycles: ", cycles)
