import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Manual smoke test for ``ClientWindow`` (window rect + crop).
import platform
import time

import cv2
import bot_env as Env
import bot_client as Client

if platform.system() == "Windows":
    import win32gui
else:
    import window_tool as Wt


def find_and_crop_client(bot, DEBUG=True):
    image = Env.screen_image(rect=None, DEBUG=DEBUG)
    image = Env.block_name(image, corner=[bot.win_rect[0], bot.win_rect[1]])
    wr = bot.win_rect
    cv2.rectangle(
        image,
        (wr[0], wr[1]),
        (wr[0] + wr[2], wr[1] + wr[3]),
        (0, 255, 0),
        2,
    )
    Env.debug_view(image, title="ClientWindow test, find client using win_rect")
    crop = Env.screen_image(rect=bot.win_rect, DEBUG=DEBUG)
    Env.debug_view(crop, title="ClientWindow test, crop client using win_rect")


if __name__ == "__main__":
    bot = Client.ClientWindow()
    find_and_crop_client(bot)
    print("MOVE THE CLIENT SOMEWHERE ELSE")
    if bot.win_rect[2] == 1920:
        bot.win_rect[2] = 1870
    if bot.win_rect[3] == 1040:
        bot.win_rect[3] = 1000
    if platform.system() == "Windows":
        win32gui.MoveWindow(bot.id, 50, 50, bot.win_rect[2], bot.win_rect[3], True)
    else:
        Wt.linux_activate_move_resize(int(bot.id), 50, 50, bot.win_rect[2], bot.win_rect[3])
    time.sleep(2)
    print("UPDATING CLIENT IMAGE")
    bot.update()
    find_and_crop_client(bot)
