# Issues and notes

## Repo-root skill scripts (not ported in bulk)

These files still **`import win32gui`** and duplicate window setup. They will **fail on Linux** until refactored to use **`core.findWindow`** or **Exodia `BotBrain`**:

`woodcutting.py`, `miner.py`, `combat.py`, `fishing.py`, `cooking.py`, `magic.py`, `smithing.py`, `prayer.py`, `thieving.py`, `herblore.py`, `fletching.py`, `feather_trade.py`, `crafting.py`, `clay_beginner_money_maker.py`, `Air_Craft.py`, `Earth_Craft.py`, `Fire_craft.py`, `osrs_walker.py`, etc.

**Exodia** (`infernal_fishing.py`, `agility.py`, …) does **not** import those; it uses **`bot_brain`** / **`bot_actions`**.

## WSLg / xdotool

- If **`xdotool search`** returns nothing, confirm the RuneLite window title contains the substring (default **`RuneLite`**).
- Wayland-only sessions may break **`xdotool`**; document your compositor here if you find a pattern.
