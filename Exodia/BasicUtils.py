import time
import random
import bot_actions as Actions

tick = 0.6

def wait_ticks(num, adj=0):
    time.sleep(num*tick + adj + random.random()/3)