# This module handles actions the bot might need to perform on a regular basis

# Imports - legs do not currently perform any task in a way it could be modulated here
import bot_client as Client
import bot_eyes as Eyes
import bot_arms as Arms
import bot_env as Env
import math
import os
import time
import random


def bgr_bounds_from_color(color, shade):
    """Return ``(lower_bgr, upper_bgr)`` tuples clamped to 0..255."""
    [b, g, r] = color
    lower = [max(b - shade, 0), max(g - shade, 0), max(r - shade, 0)]
    upper = [min(b + shade, 255), min(g + shade, 255), min(r + shade, 255)]
    return lower, upper


# Initialize the necessary objects
def bot_init(DEBUG=False, win_rect=None, window_title="RuneLite"):
    if win_rect is not None:
        client = Client.FixedClientWindow(win_rect)
    else:
        client = Client.ClientWindow(DEBUG=DEBUG, window_title_substring=window_title)
    bot_e = Eyes.BotEyes(DEBUG=DEBUG)
    bot_e.setRect(client.win_rect)
    bot_a = Arms.BotArms()
    return [client, bot_e, bot_a]


# Update window geometry only (no frame grab).
def sync_window(client, bot_e):
    client.update()
    bot_e.set_rect_geometry(client.win_rect)


# Update window geometry and refresh frame from stream or sync grab.
def bot_update(client, bot_e):
    sync_window(client, bot_e)
    bot_e.capture_frame()


# Look for either an image or a colorband in the playspace
def scan_for(b_eyes, b_arms, target="", method="image", bounds=None, attempts=10, DEBUG=False):
    # Target needs to be assigned
    if target is None:
        raise Exception('We cannot scan for nothing!')
    
    if DEBUG:
        b_eyes.force_debug(DEBUG)

    if bounds is None:
        bounds = []

    # All bot objects are good to go, start scanning
    if method == 'image':
        click_info = b_eyes.locate_image(filename=target, name=("Scanning for %s" % (target,)))
    elif method == 'color':
        click_info = b_eyes.locate_color(boundaries=bounds)

    # Image was found, Bob's your uncle
    if click_info != []:
        b_arms.click_here(click_info, center=b_eyes.local_center)
    else:
        # We did not find the object for one reason or another, try looking around? Give it 10 attemps
        attempt = 0
        while click_info == [] and attempt < attempts:
            r = random.random()
            if r > 0.5:
                b_arms.pan_right(center=b_eyes.global_center, win_rect=b_eyes.client_rect, rand=True)
            else:
                b_arms.pan_left(center=b_eyes.global_center, win_rect=b_eyes.client_rect, rand=True)
            
            b_eyes.update()

            if method == 'image':
                click_info = b_eyes.locate_image(filename=target, name=("Scanning for %s" % (target,)))
            elif method == 'color':
                click_info = b_eyes.locate_color(boundaries=bounds)
            attempt += 1

        # If we found the target
        if click_info != [] and attempt < attempts:
            print('I found the target')
            b_arms.click_here(click_info, center=b_eyes.local_center)


def use_x_on_y(
    eyes,
    arms,
    source: str,
    dest: str,
    *,
    client=None,
    inv: bool = True,
    threshold: float | None = None,
    click_rad: int | None = None,
    refresh: bool = False,
    center_first: bool = True,
    focus: bool = True,
):
    """
    OSRS inventory use-on: click source (X), then destination (Y).

    Locates both templates in the inventory crop, clears hover text when
    ``center_first`` is true, then clicks source → closest destination.

    Examples:
      use_x_on_y(eyes, arms, "imcando_hammer.png", "infernal_eel_fish.png")
      use_x_on_y(eyes, arms, "osrs_knife.png", "osrs_sacredEel.png")
    """
    from bot_inventory_actions import (
        UseItemOnResult,
        _env_float,
        clear_inventory_hover,
        focus_runelite,
        pick_distinct_screen_points,
    )

    if refresh and client is not None:
        bot_update(client, eyes)

    locate_kw: dict = {"inv": inv}
    if threshold is not None:
        locate_kw["threshold"] = threshold

    sources = eyes.locate_image(
        filename=source, name=("Scanning for %s" % source), **locate_kw
    )
    dests = eyes.locate_image(
        filename=dest, name=("Scanning for %s" % dest), **locate_kw
    )
    if not sources:
        return UseItemOnResult.fail("source_not_found", missing_item=source)
    if not dests:
        return UseItemOnResult.fail("dest_not_found", missing_item=dest)

    src_pt, dst_pt = pick_distinct_screen_points(sources, dests)
    if src_pt is None or dst_pt is None:
        return UseItemOnResult.fail("dest_not_found", missing_item=dest)

    if focus:
        focus_runelite()
        time.sleep(0.2)
    if center_first and eyes.client_rect is not None:
        clear_inventory_hover(eyes.client_rect)

    rad = click_rad
    if rad is None:
        rad = int(os.environ.get("EXODIA_INV_CLICK_RAD", "6"))

    arms.click_at(list(src_pt), rad=rad)
    gap = _env_float("EXODIA_INV_USE_ON_GAP_S", 0.18)
    time.sleep(max(0.05, gap))
    arms.click_at(list(dst_pt), rad=rad)
    return UseItemOnResult(True)


def use_item_on(b_eyes, b_arms, target_1, target_2):
    """Deprecated alias for :func:`use_x_on_y`."""
    return use_x_on_y(b_eyes, b_arms, target_1, target_2)

# Attempts to locate and click on an image within an image
def click_on_image(client, bot_arms, bot_eyes, target, refresh=True):
    if refresh:
        bot_update(client, bot_eyes)
    target = bot_eyes.locate_image(filename=target, inv=False)
    target = random.choice(target)
    bot_arms.click_at(target)

# Attempts to click on a color on the screen closest to the center of the image, if provided a target will try to click on the color near the target
def click_on_color(client, bot_arms, bot_eyes, color, shade=20, range=20, use_target=False, c_target=(0, 0), refresh=True):
    if refresh:
        bot_update(client, bot_eyes)
    color_lower, color_upper = bgr_bounds_from_color(color, shade)
    point = bot_eyes.locate_cluster(
        boundaries=[(color_lower, color_upper)],
        cluster_dist=range,
        use_target=use_target,
        c_target=c_target,
    )
    # locate cluster will return the point closest to the center of the client
    if len(point) < 2:
        return
    bot_arms.click_at(point, 9)
    # bot_arms.move_mouse(point)

# Runs the above function with enabled target params
def click_color_near_color(client, bot_arms, bot_eyes, color, target_color, shade=20, range=20):
    bot_update(client, bot_eyes)
    tl, tu = bgr_bounds_from_color(target_color, shade)
    hits = bot_eyes.locate_color(boundaries=[(tl, tu)])
    if not hits:
        c_local = (0, 0)
    else:
        gx, gy = hits[0][0], hits[0][1]
        c_local = (gx - bot_eyes.client_rect[0], gy - bot_eyes.client_rect[1])
    click_on_color(
        client,
        bot_arms,
        bot_eyes,
        color,
        shade=shade,
        range=range,
        use_target=True,
        c_target=c_local,
        refresh=False,
    )

# Checks if a color is near a target point
def color_is_close(client, bot_eyes, color, shade=10, dist=40, range=300):
    bot_update(client, bot_eyes)
    color_lower, color_upper = bgr_bounds_from_color(color, shade)
    print(color_lower)
    print(color_upper)
    point = bot_eyes.locate_cluster(boundaries=[(color_lower, color_upper)], cluster_dist=range)
    if len(point) == 2 and math.dist(bot_eyes.global_center, point) < range:
        return True
    return False

# Basically the function above
def check_color(client, bot_e, bot_color):
    b = color_is_close(client, bot_e, bot_color)
    if not b:
        print('UH OH')
        return False
    return True

# moves mouse with additional radius
def mouse_fidgit(client, bot_arms, bot_eyes, rad=200):
    #484x338
    bot_update(client, bot_eyes)
    goto = [bot_eyes.global_center[0] + 484,  bot_eyes.global_center[1] + 338]
    bot_arms.move_mouse(goto, rad=rad)


#Main
if __name__ == "__main__":
    # Initialize bot objects
    [client, bot_e, bot_a] = bot_init()

    # Env.debug_view(bot_e.curr_client, "Initial")

    # scan_for(bot_e, bot_a, target=r'magic_tree_sample.png')
    # bounds = [([0, 240, 240], [0, 255, 255])] # -> Yellow
    # scan_for(bot_e, bot_a, method='color', bounds=bounds)
    

    purple = [255, 0, 183]
    yellow = [0, 255, 255]
    cyan = [255, 255, 0]
    # bot_a.force_debug(True)
    #click_on_color(bot_a, bot_e, cyan)
    # bot_e.force_debug(True)
    for i in range(0, 15):
        click_on_color(client, bot_a, bot_e, purple)
        mouse_fidgit(client, bot_a, bot_e, rad=500)
        time.sleep(0.1)
    #click_on_color(bot_a, bot_e, yellow)

    # time.sleep(5)

    # Check if the top left of the client says "Woodcutting" or whatever
    # action = bot_e.get_action_text()
    # print(action)
    # if action != 0:
        # time.sleep(2)
        # scan_for(bot_e, bot_a, method='color', bounds=bounds)

    # Example for 'use_item_on'
    # use_item_on(bot_e, bot_a, r'knife.png', r'magic_logs.png')
    # use_item_on(bot_e, bot_a, r'magic_logs.png', r'knife.png')