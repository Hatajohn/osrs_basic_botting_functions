import bot_eyes as Eyes
import bot_env as Env
import bot_actions as Actions
import cv2

# Main
if __name__ == "__main__":
    # Initialize bot objects
    [bot_b, bot_e, bot_a] = Actions.bot_init(True)
    bot_e.force_debug(True)

    fs = Env.screen_image()
    cv2.rectangle(fs, bot_e.inventory_global, color=(0, 255, 0), thickness=2)
    Env.debug_view(fs)
    Env.debug_view(bot_e.curr_inventory)