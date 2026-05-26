"""Compound glue layer: coordinates client, eyes, and arms for multi-step bot actions.
Single-module composites (init, refresh, click, use-on) without brain or FSM logic."""

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


def bot_init(DEBUG=False, win_rect=None, window_title="RuneLite"):
    """Question: How do I create and wire client, eyes, and arms for a bot session?"""
    if win_rect is not None:
        client = Client.FixedClientWindow(win_rect)
    else:
        client = Client.ClientWindow(DEBUG=DEBUG, window_title_substring=window_title)
    bot_e = Eyes.BotEyes(DEBUG=DEBUG)
    bot_e.setRect(client.win_rect)
    bot_a = Arms.BotArms()
    return [client, bot_e, bot_a]


def sync_window(client, bot_e):
    """Question: How do I refresh window geometry without grabbing a new frame?"""
    client.update()
    bot_e.set_rect_geometry(client.win_rect)


def bot_update(client, bot_e):
    """Question: How do I refresh window geometry and capture the latest frame?"""
    sync_window(client, bot_e)
    bot_e.capture_frame()


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
    """Question: How do I use inventory item X on item Y (source then closest dest)?"""
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


def click_on_image(client, bot_arms, bot_eyes, target, refresh=True, inv=False, template_path=None):
    """Question: How do I find and click a template on screen (world or inventory)?"""
    if refresh:
        bot_update(client, bot_eyes)
    from bot_inventory_detect import bind_inventory_to_eyes

    search_roi = None
    if inv:
        bind_inventory_to_eyes(bot_eyes, refresh_client=False, force=True)
    else:
        bind_inventory_to_eyes(bot_eyes, refresh_client=False, force=False)
        from bot_template_targets import filter_matches_outside_inventory, playspace_search_roi

        search_roi = playspace_search_roi(bot_eyes)
    detailed = bot_eyes.locate_image_detailed(
        filename=target,
        inv=inv,
        template_path=template_path,
        search_roi=search_roi,
    )
    matches = list(detailed.matches) if detailed.found else []
    if not inv:
        from bot_template_targets import filter_matches_outside_inventory

        matches, _ = filter_matches_outside_inventory(bot_eyes, matches)
    if not matches:
        raise ValueError("template_not_found:%s" % target)
    best = max(matches, key=lambda m: m.score)
    from bot_inventory_actions import focus_runelite

    focus_runelite()
    time.sleep(0.2)
    bot_arms.click_at(best.screen_xy)


def click_on_color(client, bot_arms, bot_eyes, color, shade=20, range=20, use_target=False, c_target=(0, 0), refresh=True):
    """Question: How do I find and click a color cluster in the playspace?"""
    if refresh:
        bot_update(client, bot_eyes)
    color_lower, color_upper = bgr_bounds_from_color(color, shade)
    point = bot_eyes.locate_cluster(
        boundaries=[(color_lower, color_upper)],
        cluster_dist=range,
        use_target=use_target,
        c_target=c_target,
    )
    if len(point) < 2:
        return
    bot_arms.click_at(point, 9)


def color_is_close(client, bot_eyes, color, shade=10, dist=40, range=300):
    """Question: Is a color cluster within distance of screen center?"""
    bot_update(client, bot_eyes)
    color_lower, color_upper = bgr_bounds_from_color(color, shade)
    print(color_lower)
    print(color_upper)
    point = bot_eyes.locate_cluster(boundaries=[(color_lower, color_upper)], cluster_dist=range)
    if len(point) == 2 and math.dist(bot_eyes.global_center, point) < range:
        return True
    return False


def check_color(client, bot_e, bot_color):
    """Question: Does the expected color appear near center (with fail log)?"""
    b = color_is_close(client, bot_e, bot_color)
    if not b:
        print('UH OH')
        return False
    return True


def mouse_fidgit(client, bot_arms, bot_eyes, rad=200):
    """Question: How do I nudge the mouse away from center to reset hover?"""
    bot_update(client, bot_eyes)
    goto = [bot_eyes.global_center[0] + 484, bot_eyes.global_center[1] + 338]
    bot_arms.move_mouse(goto, rad=rad)


if __name__ == "__main__":
    [client, bot_e, bot_a] = bot_init()

    purple = [255, 0, 183]
    for i in range(0, 15):
        click_on_color(client, bot_a, bot_e, purple)
        mouse_fidgit(client, bot_a, bot_e, rad=500)
        time.sleep(0.1)
