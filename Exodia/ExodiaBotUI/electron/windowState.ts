import fs from 'node:fs';
import path from 'node:path';
import { app, screen, type BrowserWindow, type BrowserWindowConstructorOptions } from 'electron';

export type SavedWindowState = {
  x?: number;
  y?: number;
  width: number;
  height: number;
  isMaximized?: boolean;
};

const DEFAULTS: SavedWindowState = {
  width: 1280,
  height: 800,
  isMaximized: false,
};

export const WINDOW_MIN_WIDTH = 900;
export const WINDOW_MIN_HEIGHT = 600;

function statePath(): string {
  return path.join(app.getPath('userData'), 'window-state.json');
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function ensureOnScreen(state: SavedWindowState): SavedWindowState {
  if (state.x === undefined || state.y === undefined) return state;

  const rect = {
    x: state.x,
    y: state.y,
    width: state.width,
    height: state.height,
  };

  const visible = screen.getAllDisplays().some((display) => {
    const area = display.workArea;
    return (
      rect.x < area.x + area.width &&
      rect.x + rect.width > area.x &&
      rect.y < area.y + area.height &&
      rect.y + rect.height > area.y
    );
  });

  if (visible) return state;

  return {
    width: state.width,
    height: state.height,
    isMaximized: state.isMaximized,
  };
}

function normalizeState(parsed: Partial<SavedWindowState>): SavedWindowState {
  const width = clamp(parsed.width ?? DEFAULTS.width, WINDOW_MIN_WIDTH, 10000);
  const height = clamp(parsed.height ?? DEFAULTS.height, WINDOW_MIN_HEIGHT, 10000);
  const state: SavedWindowState = {
    width,
    height,
    isMaximized: Boolean(parsed.isMaximized),
  };
  if (typeof parsed.x === 'number' && Number.isFinite(parsed.x)) {
    state.x = Math.round(parsed.x);
  }
  if (typeof parsed.y === 'number' && Number.isFinite(parsed.y)) {
    state.y = Math.round(parsed.y);
  }
  return ensureOnScreen(state);
}

export function loadWindowState(): SavedWindowState {
  try {
    const raw = fs.readFileSync(statePath(), 'utf8');
    const parsed = JSON.parse(raw) as Partial<SavedWindowState>;
    return normalizeState(parsed);
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveWindowState(win: BrowserWindow): void {
  if (win.isDestroyed()) return;

  const isMaximized = win.isMaximized();
  const bounds = isMaximized ? win.getNormalBounds() : win.getBounds();
  const state = normalizeState({
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    isMaximized,
  });

  try {
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(state, null, 2), 'utf8');
  } catch (err) {
    console.error('Failed to save window state:', err);
  }
}

export function windowOptionsFromState(state: SavedWindowState): BrowserWindowConstructorOptions {
  const options: BrowserWindowConstructorOptions = {
    width: state.width,
    height: state.height,
    minWidth: WINDOW_MIN_WIDTH,
    minHeight: WINDOW_MIN_HEIGHT,
  };
  if (state.x !== undefined && state.y !== undefined) {
    options.x = state.x;
    options.y = state.y;
  }
  return options;
}

/** Persist bounds on move/resize (debounced) and again on close. */
export function attachWindowStatePersistence(win: BrowserWindow): void {
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      saveTimer = null;
      saveWindowState(win);
    }, 400);
  };

  win.on('resize', scheduleSave);
  win.on('move', scheduleSave);
  win.on('close', () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveWindowState(win);
  });
}

export function getWindowStatePath(): string {
  return statePath();
}
