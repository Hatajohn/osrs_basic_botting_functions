# Imports
import bot_actions as Actions
import bot_legs as Legs
import bot_eyes as Eyes
import bot_arms as Arms
import time
import random

iter = 0.1

#Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = Actions.bot_init()

    total_iter = 0
    duration=0.05
    rad=5
    amount = 15600
    while total_iter < amount:
        #fletch actions
        print(total_iter)
        #1805x754
        #click there
        bot_a.click_at([1805, 754], rad, duration)

        #1804x790
        #click there
        bot_a.click_at([1804, 790], rad, duration)
        total_iter = total_iter + 1