import type { ExodiaSettings } from './settings';

/** IPC channel names — shared between main, preload, and renderer. */
export const IPC = {
  GET_SETTINGS: 'settings:get',
  SET_SETTINGS: 'settings:set',
  SPAWN_SMOKE_TEST: 'python:spawnSmokeTest',
  APP_QUIT: 'app:quit',
  LOG_LINE: 'log:line',
  SELECT_SCRIPTS_FOLDER: 'files:selectScriptsFolder',
  LIST_DIRECTORY: 'files:listDirectory',
  REFRESH_DEBUG_FRAME: 'debug:refresh',
  SAVE_DEBUG_SNAPSHOT: 'debug:saveSnapshot',
  OPEN_LOGS_FOLDER: 'app:openLogsFolder',
  RUN_CALIBRATE_CLIENT_RECT: 'python:runCalibrateClientRect',
} as const;

export type DebugFrameMode = 'inventory_identify' | 'raw_client' | 'inventory_grid';

export type DebugFrameResult = {
  ok: boolean;
  mode: DebugFrameMode;
  path?: string;
  imageDataUrl?: string;
  occupied?: number;
  unknown?: number;
  tmpCount?: number;
  width?: number;
  height?: number;
  error?: string;
  hint?: string;
  refreshedAt?: number;
  stderr?: string;
  stdout?: string;
};

export type SaveSnapshotResult = {
  ok: boolean;
  path?: string;
  canceled?: boolean;
  error?: string;
};

export type CalibrateClientRectResult = {
  ok: boolean;
  stdout: string;
  stderr: string;
  exitCode: number | null;
  canceled?: boolean;
  error?: string;
};

export type LogLinePayload = {
  line: string;
  stream: 'stdout' | 'stderr' | 'system';
  ts: number;
};

export type SmokeTestResult = {
  ok: boolean;
  stdout: string;
  stderr: string;
  exitCode: number | null;
  error?: string;
};

export type FileEntry = {
  name: string;
  path: string;
  kind: 'file' | 'directory';
};

export type ListDirectoryResult = {
  path: string;
  parentPath: string | null;
  entries: FileEntry[];
  error?: string;
};

export type SelectFolderResult = {
  canceled: boolean;
  path?: string;
};

export type SettingsResult = {
  settings: ExodiaSettings;
  resolved: {
    exodiaRoot: string;
    pythonPath: string;
    logsDir: string;
    chainsDir: string;
    scriptsFolder: string;
  };
};

export type ExodiaApi = {
  getSettings: () => Promise<SettingsResult>;
  setSettings: (partial: Partial<ExodiaSettings>) => Promise<SettingsResult>;
  spawnSmokeTest: () => Promise<SmokeTestResult>;
  quit: () => Promise<void>;
  onLogLine: (callback: (payload: LogLinePayload) => void) => () => void;
  selectScriptsFolder: () => Promise<SelectFolderResult>;
  listDirectory: (dirPath: string) => Promise<ListDirectoryResult>;
  refreshDebugFrame: (mode?: DebugFrameMode) => Promise<DebugFrameResult>;
  saveDebugSnapshot: (imageDataUrl: string, defaultName?: string) => Promise<SaveSnapshotResult>;
  openLogsFolder: () => Promise<void>;
  runCalibrateClientRect: () => Promise<CalibrateClientRectResult>;
};

declare global {
  interface Window {
    exodia: ExodiaApi;
  }
}

export {};
