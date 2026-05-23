# Issues and notes

## 2026-05-03 — Exodia review: window_tool.py

- **Low:** Removed unused **`attempt_vis`** block (was dead code); **`only_visible`** parameter remains unused—loop always tries **`--onlyvisible`** then plain **`search`**.
- **Medium:** `linux_activate_move_resize` runs three `subprocess.run` calls with no return value or stderr surface; callers cannot tell if activate/move/size failed. Consider returning `bool` or logging on non-zero exit.
- **Low:** `metrics_from_ltrb` hard-codes **30** / **50** border heuristics (legacy win32 parity); keep in sync with any `BotBrain`/`getWindow` changes.
- **Positive:** Consistent **8s** timeouts; **`linux_search_window_id`** tries **--onlyvisible** then full **search**; geometry parsed defensively from **--shell** output.
- **Note:** Parameter **`only_visible`** is currently unused—the loop always tries both search orders. To honor the flag, skip the **`--onlyvisible`** attempt when `only_visible=False`.

## 2026-05-03 — Exodia review: bot_env.py

- **`screen_regions`**: each label calls **`screen_image`** → separate **`mss`** context per ROI under default backend; fine for few ROIs, costly for many (future: single full grab + crop if needed).
- **`block_name`**: **Fixed** — draws with **`pt1`/`pt2`** and returns the image (**`cv2.rectangle`** returns **`None`** in Python bindings).
- **`debug_view`**: **`waitKey(0)`** blocks until keypress; uses **`resize_image`** with **`scale`** as percent.
- **Positive:** **`PERF_TICK_S`**, env-driven capture backend, **`Rect`** typing.
- **`screen_image(rect=None)`**: captures the **primary monitor** via **`mss`** geometry (`monitors[1]`), then applies **`EXODIA_CAPTURE_BACKEND`** for the grab (PIL uses that bbox).

## 2026-05-03 — Exodia review: bot_brain.py

- **Unix:** **`linux_activate_move_resize(wid, 0, 0, 865, 830)`** on (re)find—**intentional** for vision-only automation: snaps client to known geometry so Eyes ROIs and **`BotArms`** clicks stay aligned without reading game memory (manual relayout after drift is brittle).
- **`get_window_rect`**: broad **`except Exception: return False`** swallows real errors; callers cannot tell “gone” vs “failed.”
- **`enum_window_callback`**: last matching visible window wins if multiple titles match substring.
- **Positive:** **`EXODIA_GEOM_MIN_INTERVAL`** throttles geometry; **`RuneLiteNotFoundException`** messages are actionable.

## Exodia BotLegs / Task

- **`update_all`** and **`Task.run`** use **`except Exception`** and print **`repr(e)`** (no bare `except`).
- **`bot_loop`**: stops when **`elapsed_ms >= _max`** (ms since start) or **`self.flag`**; waits until **`_t`** ms since last **`update_all`**, polling every **5 ms**. Use **`_t = 600`** (~**0.6 s** tick) or **`int(Env.PERF_TICK_S * 1000)`** when **`PERF_TICK_S`** is imported from **`bot_env`**.
- **`Task.run`** invokes **`getattr(self._object, self._func)`** with **`*_params`** when **`params`** is a non-empty list/tuple.
- **`to_do` / `run_tasks`**: queue is **not** auto-cleared—tasks run **every** cycle until removed (recurring-hook semantics). **Roadmap:** explicit one-shot vs recurring tasks when activities need Eyes-driven dynamic rewiring vs fixed step lists.

## Repo-root skill scripts (not ported in bulk)

These files still **`import win32gui`** and duplicate window setup. They will **fail on Linux** until refactored to use **`core.findWindow`** or **Exodia `BotBrain`**:

`woodcutting.py`, `miner.py`, `combat.py`, `fishing.py`, `cooking.py`, `magic.py`, `smithing.py`, `prayer.py`, `thieving.py`, `herblore.py`, `fletching.py`, `feather_trade.py`, `crafting.py`, `clay_beginner_money_maker.py`, `Air_Craft.py`, `Earth_Craft.py`, `Fire_craft.py`, `osrs_walker.py`, etc.

**Exodia** (`infernal_fishing.py`, `agility.py`, …) does **not** import those; it uses **`bot_brain`** / **`bot_actions`**.

## 2026-05-03 — Exodia review: bot_arms.py

- **Fixed:** **`pan_up`** / **`pan_down`** built a **3-element** `point` list (duplicate `center[1]`); **`control_camera`** expects **[x, y]** — corrected to two components.
- **Fixed:** **`drop_all`** uses **`try`/`finally`** so **`shift`** is released on errors.
- **Fixed:** **`click_at`** rejects **`None`** and non-pair **`point`** early.
- **Low:** **`keep_point_on_screen`** always **`print('CLAMP x y')`**—noisy in production loops.
- **Note:** Author comment on **`hit_escape`** (“THIS DOES NOT WORK”)—verify on target OS / focus policy.
- **Positive:** Bezier **`splprep`** failures fall back to straight **`moveTo`**; **`move_profile`** maps to conservative tween pools (see **`input_safety.md`**).

## 2026-05-03 — Exodia review: bot_legs.py + bot_bag.py

- **`bot_legs`**: **`bot_loop`**/docstring align—exit when **`elapsed_ms >= _max`** or **`flag`**; spacing uses **`time.sleep(0.005)`** between polls when under **`_t`**.
- **`Task.run`**: with **`_object is None`**, calls **`self._func(self._params)`**—passes params as a **single** argument (document when using free functions).
- **`add_task`**: parameter name **`object`** shadows builtin—rename in a future cleanup pass.
- **`bot_bag`**: stub **4×7** grid only; **not** wired to **`BotEyes`**—keep as placeholder or delete when inventory modeling lives elsewhere.

## 2026-05-03 — Exodia review: activity scripts

- **`infernal_fishing.py`**: **`keep_fishing`**—added missing **`bot_b`** parameter (was **`NameError`**). Main loop uses **`action_code`** from **`get_action_text()`** instead of overwriting string **`state`** with an int. Main **`__main__`** loop uses **`time.monotonic()`**, **`interval_s`**, and a **`timer_session_ms`** wall cap (legacy literal interpreted as ms).
- **`agility.py`** / **`BasicUtils.py`**: Both use **`constants.OSRS_TICK_S`** via **`wait_ticks`**; shared constant lives in **`Exodia/constants.py`** ( **`bot_env.PERF_TICK_S`** aliases the same value).
- **`WhyFletch.py`**: Pixel-hard-coded clicks; fragile across resolutions. Renamed **`iter`** → **`pause_seconds`** (avoids shadowing **`builtins.iter`**).
- **`BasicUtils.py`**: Thin **`wait_ticks`** only; merge with **`agility`** when refactoring.

## 2026-05-03 — Exodia review: tests + harnesses

- **`bot_test.py`**: Legacy fragment / stale API (**`locate_image(image, ...)`** vs **`BotEyes.locate_image`**); treat as archive or rewrite before use.
- **`bot_env_test.py`**, **`bot_brain_test.py`**: Reasonable manual smoke paths.
- **`bot_eyes_test.py`**: Guard **`locate_cluster`** result length before **`cv2.circle`** when extending tests.

## 2026-05-03 — Exodia review: requirements / config

- **`requirements-linux.txt`**: No **`pywin32`**—correct; system **tesseract-ocr**, **xdotool** per header.
- **`requirements.txt`**: Optional audit for unused deps (**`keyboard`**, **`shapely`**, **`pyscreenshot`**, etc.) vs actual imports.

## 2026-05-03 — Exodia review sweep (pointer)

Per-file and holistic notes live under dated **`## 2026-05-03`** headings in this file; high-level flow themes are summarized in **`Corpus/exodia_architecture.md`** → **Holistic flow review**.

## WSLg / xdotool

- If **`xdotool search`** returns nothing, confirm the RuneLite window title contains the substring (default **`RuneLite`**).
- Wayland-only sessions may break **`xdotool`**; document your compositor here if you find a pattern.
