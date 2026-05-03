# Repo-root `core.py` (Linux)

- **`win32gui`** is imported **only on Windows**.
- **`Exodia/`** is prepended to **`sys.path`** so **`import window_tool`** works from repo root.
- **`findWindow` / `getWindow`** on Linux use **`window_tool`** (`xdotool`) the same way **`BotBrain`** does.
- Module import still loads **`pybot-config.yaml`** and runs **`findWindow(client_title)`** — behavior unchanged, but now **importable on Linux** without `pywin32`.

**Note:** Many **skill scripts** in repo root (`woodcutting.py`, `miner.py`, …) still **`import win32gui` directly**. They were **not** bulk-ported; use **Exodia** for new Linux work, or refactor those scripts to call **`core.findWindow`** / shared helpers when needed. See **`issues_and_notes.md`**.
