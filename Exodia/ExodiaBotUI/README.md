# Exodia Desktop (Phase 0)

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

## Phase 0 features

- **Menu bar** — custom React dropdown menus (cross-platform; native `Menu.buildFromTemplate` deferred to macOS polish in Phase 7)
- **Four-quadrant dashboard** — Log | RuneLite view + Bot tasks | Scripts and actions
- **Preferences** — File → Preferences… or `Ctrl+,`; settings persist in Electron `userData/config.json`
- **Smoke test** — Preferences → Run smoke test spawns `{python} -c "print('ok')"` and streams output to the Log panel
- **File → Clear log**, **File → Quit** (`Ctrl+Q`), **Help → About**

## Settings

| Key | Default |
|-----|---------|
| `exodiaRoot` | Parent of `ExodiaBotUI/` |
| `pythonPath` | `{exodiaRoot}/exodia/bin/python` if present, else `python3` |
| `logsDir` | `{exodiaRoot}/logs` |
| `chainsDir` | `{exodiaRoot}/ExodiaBotUI/chains` |
| `streamPort` | `8765` |

Leave `pythonPath` blank to use the venv default. An invalid path shows an error in Preferences after save or smoke test.

## Project layout

```
ExodiaBotUI/
  electron/     Main process, preload, paths, settings
  shared/       IPC channel names and types
  src/          React renderer (menu, dashboard, panels)
```

## WSL / Windows

`electron/paths.ts` exposes `detectPlatform()` (`linux`, `wsl`, `win32`, `darwin`) for future platform-specific defaults. Phase 0 uses the same path resolution on all platforms.

## Build

```bash
npm run build
```

Production build output: `dist/` (renderer) and `dist-electron/` (main/preload). Run Electron against the built artifacts for packaging in Phase 7.
