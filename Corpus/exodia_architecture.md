# Exodia architecture

Exodia modules are named to keep **clear responsibilities** (Yu-Gi-Oh “pieces” metaphor):

| Module | Responsibility |
|--------|----------------|
| **bot_brain** | Locate the game window; expose `win_rect` `[left, top, width, height]` for capture and clicks. |
| **bot_env** | Screenshots (`screen_image`), CV helpers, `debug_view`, **`human_pause`** (variable delays). |
| **window_tool** | **Linux/WSLg:** `xdotool` subprocess bridge (search, geometry, activate/move/resize). No extra PyPI deps. |
| **bot_arms** | Mouse/keyboard via PyAutoGUI. |
| **bot_legs** | Session loop / orchestration (`update_all`, timers). |
| **bot_eyes** | Vision + OCR (OpenCV, pytesseract). |
| **bot_bag** | Inventory-oriented state (uses Eyes/Env). |
| **bot_actions** | Composes Brain + Eyes + Arms for higher-level flows. |

**Dependency direction:** `bot_actions` → brain, eyes, arms, env. **Avoid** arms importing eyes unless necessary; keep OS/window logic in **brain** + **window_tool**, not scattered in skill scripts.

Porting rule: Windows still uses **pywin32** inside `bot_brain` only; Linux uses **window_tool** only.
