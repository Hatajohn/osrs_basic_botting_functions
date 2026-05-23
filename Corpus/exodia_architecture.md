# Exodia architecture

Exodia modules are named to keep **clear responsibilities** (Yu-Gi-Oh “pieces” metaphor):

| Module | Responsibility |
|--------|----------------|
| **bot_brain** | Locate the game window; expose `win_rect` `[left, top, width, height]` for capture and clicks. |
| **constants** | **`OSRS_TICK_S`** (~0.6 s game tick). **`bot_env.PERF_TICK_S`** aliases it; skill scripts import **`constants`** for sleeps without **`bot_env`**. |
| **bot_env** | **`PERF_TICK_S`** (from **`constants`**), **`screen_image`**, **`screen_regions`**, capture backend env, `debug_view`, **`human_pause`**. |
| **window_tool** | **Linux/WSLg:** `xdotool` subprocess bridge (search, name, geometry, activate/move/resize). No extra PyPI deps. |
| **bot_arms** | Mouse via PyAutoGUI; **`move_profile`** (`tight` / `normal` / `open`) — see **`Corpus/input_safety.md`**. |
| **bot_legs** | Session loop / orchestration (`update_all`, timers). |
| **bot_eyes** | Vision + OCR (`run_ocr`, template match, optional **`search_roi`**). |
| **bot_bag** | Stub **4×7** inventory grid only—not wired to **BotEyes** today (placeholder). |
| **bot_actions** | Composes Brain + Eyes + Arms for higher-level flows. |

**Dependency direction:** `bot_actions` → brain, eyes, arms, env. **Avoid** arms importing eyes unless necessary; keep OS/window logic in **brain** + **window_tool**, not scattered in skill scripts.

Porting rule: Windows still uses **pywin32** inside `bot_brain` only; Linux uses **window_tool** only.

## 2026-05-03 — Holistic flow review

**Runtime path.** Skill scripts (**`infernal_fishing`**, **`agility`**, **`WhyFletch`**) typically call **`Actions.bot_init()`** → **`BotBrain`** sets **`win_rect`** → **`BotEyes.setRect`** primes capture → loops use **`Actions.bot_update`**, **`locate_*`**, **`click_on_*`**, **`BotArms`**. **`BotLegs`** exists but several scripts still use hand-rolled **`while`** + **`time`** instead of **`bot_loop`** / **`Task`**.

**Improvement themes.** (1) Shared **`wait_ticks`** / tick helper (**`agility`** vs **`BasicUtils`**). (2) Resolution-independent coords (**`WhyFletch`** hard-coded pixels). (3) Replace or archive **`bot_test.py`** (stale API). (4) Trim **`requirements*.txt`** after import audit. (5) Keep **`Corpus/issues_and_notes`** dated sections aligned with code fixes.

**Suggested phases (later).** Extract tick helper → **`bot_env.block_name`** uses **`pt1`/`pt2`** + returns image → migrate one script to **`BotLegs`** → thin requirements.

File-level notes: **`Corpus/issues_and_notes.md`** (2026-05-03 headings).
