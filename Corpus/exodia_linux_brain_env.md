# Linux: BotBrain, window_tool, bot_env

## BotBrain

- **Windows:** unchanged pattern — `EnumWindows` + `GetWindowRect`; `self.id` is HWND.
- **Linux/WSLg:** `self.id` is the numeric **xdotool window id**. `_find_window_unix` requires **`xdotool` on PATH** (`sudo apt install xdotool` in Debian/Ubuntu/WSL).
- Constructor: `BotBrain(DEBUG=False, window_title_substring="RuneLite")`. Substring is passed to `xdotool search --name`.
- On Linux, after find, **`linux_activate_move_resize`** moves/resizes toward **865×830@0,0** (parity with old `core.py` / win32 `MoveWindow`).
- **Exception:** `RuneLiteNotFoundException` if the window cannot be found or `xdotool` is missing.

## window_tool (`Exodia/window_tool.py`)

- **`linux_search_window_id`**: tries `--onlyvisible` first, then full search.
- **`linux_window_geometry`**: parses `getwindowgeometry --shell`.
- **`linux_activate_move_resize`**: `windowactivate`, `windowmove`, `windowsize`.
- **`metrics_from_ltrb`**: border heuristics used by repo-root **`core.getWindow`** only (not `BotBrain.win_rect`).

## bot_env.screen_image

- Contract unchanged: `rect` is `[left, top, width, height]`; bbox for PIL is `(left, top, left+width, top+height)`.
- **`human_pause(base_seconds, jitter_ratio=0.35)`** — small helper for less uniform sleep patterns; use from loops/`BotArms` as you refine behavior.

## WSLg caveats

`xdotool` targets **X11**. Under pure Wayland or odd WSLg compositor setups, search/geometry may fail — document your session in **`issues_and_notes.md`** if you hit this.
