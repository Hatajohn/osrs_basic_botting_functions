# Imports
import bot_env as env
import bot_brain as brain
import win32gui
import cv2
import time

def find_and_crop_client(bot, DEBUG=True):
    image = env.screen_image(block=True, cover_name=[bot.win_rect[0], bot.win_rect[1]], DEBUG=DEBUG)
    image = cv2.rectangle(image, bot.win_rect, color=(0,255,0), thickness=2)
    env.debug_view(image, title='BotBrain test, find client using win_rect')
    image = env.screen_image(rect=bot.win_rect, block=True, DEBUG=DEBUG)
    env.debug_view(image, title='BotBrain test, crop client using win_rect')

#Main
if __name__ == "__main__":
    bot = brain.BotBrain()
    find_and_crop_client(bot)
    print('MOVE THE CLIENT SOMEWHERE ELSE')
    if bot.win_rect[2] == 1920:
        bot.win_rect[2] = 1870
    if bot.win_rect[3] == 1040:
        bot.win_rect[3] = 1000
    win32gui.MoveWindow(bot.id, 50, 50, bot.win_rect[2], bot.win_rect[3], True)
    time.sleep(2)
    print('UPDATING CLIENT IMAGE')
    bot.update()
    find_and_crop_client(bot)