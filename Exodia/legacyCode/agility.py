"""Legacy Seers agility course — color-highlight clicks (example only)."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import bot_actions as Actions
import BasicUtils

# Main
if __name__ == "__main__":
    # Initialize bot objects
    [client, bot_e, bot_a] = Actions.bot_init()

    # This is a little wack. Aside from the format being BGR, I'm not sure how to get around identifying the location of the
    # highlighted agility obstacle otherwise
    purple = [255, 0, 183]
    fail_limit = 10

    for i in range(100):
        # SEERS
        # Wall
        while True:
            Actions.click_on_color(client, bot_a, bot_e, purple)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            # step 1, 12 ticks minm
            BasicUtils.wait_ticks(9, 0.05)
            if Actions.check_color(client, bot_e, (0, 0, 207)):
                break

        # Jump
        while True:
            Actions.click_on_color(client, bot_a, bot_e, purple)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            # step 2, 12 ticks min
            BasicUtils.wait_ticks(11, 0.05)
            if Actions.check_color(client, bot_e, (122, 125, 38)):
                break

        # Rope
        while True:
            Actions.click_on_color(client, bot_a, bot_e, purple)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            # step 3, 14 ticks min
            BasicUtils.wait_ticks(14, 0.15)
            if Actions.check_color(client, bot_e, (208, 0, 0)):
                break

        # Jump
        while True:
            Actions.click_on_color(client, bot_a, bot_e, purple)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            # step 4, 7 ticks min
            BasicUtils.wait_ticks(5, 0.6)
            if Actions.check_color(client, bot_e, (0, 205, 205)):
                break

        # Jump
        while True:
            Actions.click_on_color(client, bot_a, bot_e, purple)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            # step 5, 11 ticks min
            BasicUtils.wait_ticks(9, 0.05)
            if Actions.check_color(client, bot_e, (245, 245, 0)):
                break

        while True:
            Actions.click_on_color(client, bot_a, bot_e, purple, range=50)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            # step 6, 6 ticks min
            BasicUtils.wait_ticks(4, 0.3)    # teleport, 5 ticks min
            if Actions.check_color(client, bot_e, (0, 105, 252)):
                break

        icon = r'teleport_to_camelot.png'
        while True:
            Actions.bot_update(client, bot_e)
            click_info = bot_e.locate_image(filename=icon, inv=True, name='teleport to camelot')
            bot_a.click_at(click_info[0], 4)
            Actions.mouse_fidgit(client, bot_a, bot_e)
            BasicUtils.wait_ticks(3, 0.3)
            if Actions.check_color(client, bot_e, (0, 255, 0)):
                break
        print('LAP DONE')
