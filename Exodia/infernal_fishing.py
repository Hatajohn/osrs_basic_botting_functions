# Imports
import bot_actions as Actions
import bot_legs as Legs
import bot_eyes as Eyes
import bot_arms as Arms


def keep_fishing(bot_e, bot_a, bot_l, state):
    action = bot_e.get_action_text()
    if action != 0:
        # Figure out why we are not fishing
        eels_inv = bot_e.locate_image(bot_e.curr_inventory, filename=r'infernal_eel.fish.png', inv=True, name='Checking inventory')
        state = 'idle' if (len(eels_inv) == 0) else 'cracking'
        if len(eels_inv) == 22 or state == 'cracking':
            # Inv is full, crack the eels
            print('Crack the eels')
            Actions.use_item_on(bot_e, bot_a, r'imcando_hammer.png', r'infernal_eel_fish.png')
        else:
            print('Looking for eels')
            Actions.scan_for(bot_e, bot_a, r'infernal_eel_spot.png', method='color', bounds=[([235, 255, 0], [250, 255, 0])])
    else:
        # We are fishing, keep fishing
        print('Currently fishing for eels')
        pass

#Main
if __name__ == "__main__":
    [bot_b, bot_e, bot_a] = Actions.bot_init()
    bot_l = Legs.BotLegs(mods=[bot_b, bot_e])

    fishing_task = bot_l.add_task(func='keep_fishing', params=[bot_e, bot_a, bot_l, 'idle'])
    bot_l.bot_loop()

    # keep_fishing(bot_e, bot_a, bot_l, 'idle')

    