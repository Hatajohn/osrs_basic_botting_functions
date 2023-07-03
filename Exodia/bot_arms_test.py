# Import
import bot_env as env
import bot_eyes as eyes
import bot_arms as arms
import bot_brain as brain
import time
import random


# Example
# Locates and clicks the logout button at the bottom of inv, then clicks the actual logout button
#Main
if __name__ == "__main__":
    bot_b = brain.BotBrain()
    bot_e = eyes.BotEyes()
    bot_e.setRect(bot_b.win_rect)
    bot_a = arms.BotArms()
    FAST = False
    DEBUG = False

    icons = [r'inventory_icon.png', r'gear_icon.png', r'prayer_icon.png', r'standard_spells_icon.png',
             r'combat_styles_icon.png', r'tasks_icon.png', r'stats_icon.png', r'emotes_icon.png',
             r'settings_icon.png', r'friends_list_icon.png', r'account_mgmt_icon.png', r'grouping_icon.png',
             r'music_icon.png']
    random.shuffle(icons)

    corner = [bot_b.win_rect[0], bot_b.win_rect[1]]
    image = env.screen_image(bot_b.win_rect, cover_name=corner)
    env.debug_view(image, title='Bot Arms Test init')

    bot_e.update() # - > refresh inventory and client view

    click_info = bot_e.locate_image(bot_e.curr_client, filename=r'logout_button.png', name='Find logout button')
    # DOES NOT YET ACCOUNT FOR THE WORLD SWITCHER BEING OPEN!!!
    if not FAST:
        bot_a.click_here(click_info, center=bot_e.local_center, rect=bot_b.win_rect)
    else:
        # Hit ESC and click the logout button asap
        bot_a.hit_escape()
        
    time.sleep(random.uniform(0.03, 0.09))
    # Small pause before grabbing a new image and clicking logout

    bot_e.update() # - > refresh inventory and client view

    # Since I am looking at a location in the inventory I need to adust using the top left corner of the inventory -> handled by 'inv' flag
    click_info = bot_e.locate_image(bot_e.curr_inventory, inv=True, filename=r'logout_button2.png', name='Find Click here to logout')
    try:
        time.sleep(random.uniform(0.03, 0.09))
        bot_a.move_mouse(click_info[0])
    except:
        print('Could not find logout button')

    bot_e.update() # - > refresh inventory and client view

    print(icons)
    for icon in icons:
        click_info = bot_e.locate_image(bot_e.curr_client, filename=icon, name='Hit icons in a random order')
        try:
            bot_a.click_here(click_info, center=bot_e.local_center, rect=bot_b.win_rect)
        except:
            print('Could not find: ', icon)

    click_info = bot_e.locate_image(bot_e.curr_client, filename=r'login_button.png', name='LOGIN')
    bot_a.click_here(click_info, center=bot_e.local_center, rect=bot_b.win_rect)