# Exodia Desktop

Electron control shell for the Exodia Python automation harness.

## Prerequisites

- **Node.js 20+**
- Exodia repo with optional Python venv at `{exodiaRoot}/exodia/` (used as default interpreter)

## Development

```bash
cd ExodiaBotUI
npm install
npm run dev
```

`npm run dev` starts Vite with HMR and launches Electron when the dev server is ready.

**WSL / Linux:** If you see an empty window frame with no UI, the app disables GPU acceleration automatically on Linux. Restart after pulling latest changes, or run:

```bash
EXODIA_DEVTOOLS=1 npm run dev
```

to open DevTools and check the console.

## Dashboard

Four-quadrant layout:

| Region | Panel | Purpose |
|--------|-------|---------|
| Left | Log | Subprocess stdout/stderr (bots, calibration, smoke test) |
| Center top | RuneLite view | Debug inventory overlay (F5) or live MJPEG preview while agent runs |
| Center bottom | Current bot tasks | Active bot, runtime status chips |
| Right top | Scripts → Bots / Specs | Load markdown task specs and start the agent |
| Right bottom | Actions | Simple actions and chains (later phases) |

## Task specs (Bots + Specs tabs)

The agent reads **markdown spec files** (`.md`) to understand what to do.

1. **Scripts → Specs** — browse folders (markdown files and directories only). Set the root folder via **Choose folder…** or **File → Preferences…** (`scriptsFolder`).
2. Select a `.md` file → **Load into Bots**, or double-click the file.
3. **Scripts → Bots** — review loaded specs (preview, remove, clear). Click **Start agent** to run `run_agent.py` with `--spec` for each loaded file.

Loaded spec paths are passed to Python as:

```bash
python run_agent.py --brain reference_fishing --stream-port 8765 --spec /path/to/task.md
```

Startup logs print a short preview of each spec. Runtime status includes `context.spec_files`.

## Phase status

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Foundation | **Complete** | Menu, dashboard, Preferences, smoke test, log console |
| 1 — Debug vision | **Complete** | Debug frame refresh, calibrate, save snapshot |
| 2 — Bot launcher | **Complete** | See below |
| 3+ | Not started | Simple actions, chains, play-by-play, tools, packaging |

### Phase 2 — complete

Delivered:

- Process manager with Start / Stop / Pause / Resume and single-active-bot guard
- Subprocess stdout/stderr streamed to the Log panel in real time
- Runtime status polling (`logs/runtime_status.json`) in **Current bot tasks**
- Live MJPEG preview (`game_preview`) while the agent runs with `--stream-port`
- `run_agent.py` RuntimeBridge (stop, pause, resume, health) and `--spec` for markdown task files
- **Specs** tab (markdown-only file tree) → **Bots** tab (loaded spec preview + **Start agent**)

Intentional deltas from the original plan:

- **Bots tab** is spec-driven (markdown task files), not a manifest bot picker. `bots.manifest.json` still defines the agent runner internally.
- **Sacred eel** is not exposed in the Bots UI; start via CLI (`python -m SacredEelFishing.sacred_eel_fishing`). Process manager still supports manifest bots if re-exposed later.
- **File → Save session snapshot** remains stubbed (Phase 7).
- Agent **brain reading spec content** is wired at the CLI/status layer; full planner integration is a follow-up (see `FUNCTIONS.md` §9).

## Phase features (reference)

### Foundation (Phase 0)

- Menu bar, Preferences, smoke test, log console
- Settings persist in Electron `userData/config.json`

### Debug vision (Phase 1)

- **Refresh** / **F5** — inventory identify overlay via `exodia_debug_frame.py`
- **Calibrate** — `calibrate_client_rect.py` ROI picker
- **View → Save RuneLite snapshot**

### Bot launcher (Phase 2)

- Spec-driven **Start agent** with live log streaming
- **Stop / Pause / Resume** (Bot menu + Bots tab)
- Runtime status polling from `logs/runtime_status.json`
- Live MJPEG preview when agent uses `--stream-port`

## Settings

| Key | Default |
|-----|---------|
| `exodiaRoot` | Parent of `ExodiaBotUI/` |
| `pythonPath` | `{exodiaRoot}/exodia/bin/python` if present, else `python3` |
| `logsDir` | `{exodiaRoot}/logs` |
| `chainsDir` | `{exodiaRoot}/ExodiaBotUI/chains` |
| `scriptsFolder` | `{exodiaRoot}` — root for **Specs** tab markdown browser |
| `streamPort` | `8765` |

Leave `pythonPath` blank to use the venv default. An invalid path shows an error in Preferences after save or smoke test.

Point `scriptsFolder` at a folder of task specs (e.g. `PlansTODO/` or a dedicated `specs/` directory).

## Project layout

```
ExodiaBotUI/
  bots.manifest.json   Agent runner definition (used internally by Start agent)
  electron/            Main process, preload, paths, settings, process manager
  shared/              IPC types, bot manifest types, spec types
  src/                 React renderer (menu, dashboard, panels)
```

## WSL / Windows

`electron/paths.ts` exposes `detectPlatform()` (`linux`, `wsl`, `win32`, `darwin`) for future platform-specific defaults.

## Build

```bash
npm run build
```

Production build output: `dist/` (renderer) and `dist-electron/` (main/preload).
