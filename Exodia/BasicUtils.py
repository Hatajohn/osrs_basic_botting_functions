import time
import random

import bot_actions as Actions
import constants


def wait_ticks(num, adj=0):
    time.sleep(num * constants.OSRS_TICK_S + adj + random.random() / 3)