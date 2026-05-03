# Automation quality (milestone)

## Implemented in this branch

- **`bot_env.human_pause(base_seconds, jitter_ratio=0.35)`** — sleeps a **randomized** duration around `base_seconds` so loops are less perfectly periodic.

## Suggested next steps (not done here)

- Call `human_pause` from **`BotArms`** after clicks or between path segments.
- Session caps / random breaks in **`BotLegs`** (`_max`, `to_do` scheduling).
- Review **`pyautogui.PAUSE`** / MINIMUM_* settings in `BotArms.__init__` for your risk tolerance.
