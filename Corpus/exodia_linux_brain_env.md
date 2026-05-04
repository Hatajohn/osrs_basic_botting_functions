# Linux: BotBrain, window_tool, bot_env

## BotBrain

- **Windows:** `EnumWindows` + `GetWindowRect`; **`update()`** reuses HWND when **`IsWindow`** and only calls **`GetWindowRect`** if **`EXODIA_GEOM_MIN_INTERVAL`** (default **0.15** s) has elapsed — avoids hammering Win32 on tight loops.
- **Linux/WSLg:** `self.id` is the **xdotool window id**. Initial **`_find_window(force=True)`** searches, activates, resizes. Later **`update()`** uses **`getwindowname` + `getwindowgeometry`** only when the interval elapsed; full re-search if the window is gone or title mismatch.
- Env **`EXODIA_GEOM_MIN_INTERVAL`**: seconds between cheap geometry refreshes (float string, e.g. `0.12`).
- Constructor: `BotBrain(DEBUG=False, window_title_substring="RuneLite")`.
- **Exception:** `RuneLiteNotFoundException` if the window cannot be found or `xdotool` is missing (Linux).

## window_tool (`Exodia/window_tool.py`)

- **`linux_search_window_id`**: `--onlyvisible` first, then full search.
- **`linux_window_name`**: **`getwindowname`** for stale-id checks.
- **`linux_window_geometry`**: **`getwindowgeometry --shell`**.
- **`linux_activate_move_resize`**: used on **full find** only (not on every refresh).
- **`metrics_from_ltrb`**: used by repo-root **`core.getWindow`**.

## bot_env

- **`PERF_TICK_S = 0.6`** — OSRS tick hint for loop authors; align sense/act when you care about tick fidelity.
- **`EXODIA_CAPTURE_BACKEND`**: **`mss`** (default, listed in requirements) or **`pil`** for PIL/ImageGrab only (same `rect` contract `[left, top, w, h]`).
- **`screen_image` / `screen_image_fast`**: BGR output; **`screen_regions([("label", rect), ...])`** → `dict` of label → image for multi-ROI single-tick grabs.
- **`human_pause`**: short variable sleeps (flow-friendly).

## WSLg caveats

`xdotool` is **X11**-oriented; document failures under Wayland-only sessions in **`issues_and_notes.md`**.
