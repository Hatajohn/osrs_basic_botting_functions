"""Legacy fletching — fixed monitor coordinates (example only, not portable)."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import bot_actions as Actions

pause_seconds = 0.1

# Main
if __name__ == "__main__":
    # Initialize bot objects
    [client, bot_e, bot_a] = Actions.bot_init()

    total_iter = 0
    duration = 0.05
    rad = 5
    amount = 15600
    while total_iter < amount:
        # fletch actions
        print(total_iter)
        # 1805x754 — click there
        bot_a.click_at([1805, 754], rad, duration)

        # 1804x790 — click there
        bot_a.click_at([1804, 790], rad, duration)
        total_iter = total_iter + 1
