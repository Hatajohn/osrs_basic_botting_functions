import type {
  BotManifestEntry,
  BotRunInfo,
  RuntimeStatusPayload,
  StartBotRequest,
  StartBotResult,
  StopBotResult,
  RuntimeCommandResult,
} from './bots';
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
  READ_TEXT_FILE: 'files:readTextFile',
  REFRESH_DEBUG_FRAME: 'debug:refresh',
  SAVE_DEBUG_SNAPSHOT: 'debug:saveSnapshot',
  OPEN_LOGS_FOLDER: 'app:openLogsFolder',
  RUN_CALIBRATE_CLIENT_RECT: 'python:runCalibrateClientRect',
  LIST_BOTS: 'bots:list',
  GET_BOT_RUN: 'bots:getRun',
  START_BOT: 'bots:start',
  STOP_BOT: 'bots:stop',
  BOT_RUNTIME_CMD: 'bots:runtimeCmd',
  BOT_RUN_UPDATE: 'bots:runUpdate',
  BOT_STATUS_UPDATE: 'bots:statusUpdate',
  FETCH_GAME_PREVIEW: 'preview:fetchGamePreview',
  FETCH_INVENTORY_OVERLAY: 'preview:fetchInventoryOverlay',
  FETCH_PRISTINE_CLIENT: 'preview:fetchPristineClient',
  GET_STREAM_STATUS: 'stream:getStatus',
  START_STREAM: 'stream:start',
  STOP_STREAM: 'stream:stop',
  INVALIDATE_STREAM_CACHE: 'stream:invalidateCache',
  RESTART_STREAM: 'stream:restart',
  STREAM_STATUS_UPDATE: 'stream:statusUpdate',
  FETCH_STREAM_META: 'stream:fetchMeta',
  LIST_ACTION_BLOCKS: 'actions:listBlocks',
  RUN_SINGLE_ACTION: 'actions:runSingle',
  SELECT_TEMPLATE_FILE: 'files:selectTemplateFile',
  LIST_ITEM_CATALOG: 'items:listCatalog',
  RESOLVE_TEMPLATE_ITEM: 'items:resolveTemplate',
  SAVE_TEMPLATE: 'templates:save',
} as const;

export type ItemCatalogEntry = {
  id: string;
  itemId: string;
  displayName: string;
  kind: 'named' | 'fingerprint';
  templateFile?: string | null;
  templatePath?: string | null;
};

export type ItemCatalogListResult = {
  ok: boolean;
  error?: string;
  itemsDir?: string;
  named: ItemCatalogEntry[];
  fingerprints: ItemCatalogEntry[];
};

export type SaveTemplateRequest = {
  mode: 'inventory' | 'world' | 'import';
  name: string;
  dest?: 'items' | 'images';
  slot?: [number, number];
  rect?: [number, number, number, number];
  sourcePath?: string;
  overwrite?: boolean;
};

export type SaveTemplateResult = {
  ok: boolean;
  error?: string;
  hint?: string;
  kind?: 'inventory' | 'world';
  dest?: 'items' | 'images';
  itemId?: string;
  displayName?: string;
  templateFile?: string;
  templatePath?: string;
  slot?: [number, number];
  rect?: [number, number, number, number];
};

export type ResolveTemplateItemResult = {
  ok: boolean;
  error?: string;
  matched?: boolean;
  kind?: 'named' | 'fingerprint';
  itemId?: string;
  displayName?: string;
  score?: number;
  templateFile?: string;
  templatePath?: string;
  bestNamed?: string;
  bestNamedScore?: number;
  bestFingerprintScore?: number;
};

export type ActionParamDef = {
  name: string;
  type: string;
  required?: boolean;
  label?: string;
};

export type ActionBlockDef = {
  id: string;
  category: string;
  label: string;
  sideEffects: 'input' | 'none';
  params?: ActionParamDef[];
};

export type RunSingleActionRequest = {
  blockId: string;
  args?: Record<string, string>;
  dryRun?: boolean;
};

export type MatchCandidatePreview = {
  clickClientXY: [number, number];
  score?: number;
  selected?: boolean;
  searchMode?: 'inventory' | 'playspace';
};

/** Click / use-on target for RuneLite view overlay (client-local coords on captured frame). */
export type ActionClickPreview = {
  blockId: string;
  label?: string;
  previewMode?: 'click' | 'use_on' | 'find';
  searchMode?: 'inventory' | 'playspace';
  /** Single-click template actions. */
  screenXY?: [number, number];
  clickClientXY?: [number, number];
  /** Use item on item: first click (source) then second (dest). */
  fromClientXY?: [number, number];
  toClientXY?: [number, number];
  fromScreenXY?: [number, number];
  toScreenXY?: [number, number];
  sourceId?: string;
  destId?: string;
  frameWidth: number;
  frameHeight: number;
  score?: number;
  slot?: string;
  /** Other template peaks (non-selected show as dim markers on overlay). */
  matchCandidates?: MatchCandidatePreview[];
  matchCount?: number;
};

export type RunSingleActionResult = {
  ok: boolean;
  blockId: string;
  durationMs?: number;
  error?: string;
  result?: Record<string, unknown>;
  clickPreview?: ActionClickPreview;
  stderr?: string;
  stdout?: string;
};

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

export type ListDirectoryOptions = {
  /** When true, list directories plus `.md` files only. */
  markdownOnly?: boolean;
};

export type ListDirectoryResult = {
  path: string;
  parentPath: string | null;
  entries: FileEntry[];
  error?: string;
};

export type ReadTextFileResult = {
  ok: boolean;
  path: string;
  name?: string;
  content?: string;
  error?: string;
};

export type SelectFolderResult = {
  canceled: boolean;
  path?: string;
};

export type SelectTemplateFileResult = {
  canceled: boolean;
  ok?: boolean;
  error?: string;
  /** Full path on disk */
  path?: string;
  /** Basename used as ``template`` arg (e.g. flax.png) */
  name?: string;
  template?: string;
  /** Set when file is outside ``{exodiaRoot}/images`` — passed to Python locate */
  templatePath?: string;
  /** Hint for Actions panel preset messaging */
  role?: 'fishing_spot' | 'inventory_item';
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

export type GamePreviewResult = {
  ok: boolean;
  imageDataUrl?: string;
  fetchedAt?: number;
};

export type PerceptionMeta = {
  occupied?: number;
  unknown?: number;
  tmp_count?: number;
  inventory_calibrated?: boolean;
  vision_fps?: number;
  dirty_slots?: number[][];
};

export type StreamMeta = {
  capture_seq?: number;
  processed_seq?: number;
  capture_fps?: number;
  vision_fps?: number;
  perception?: PerceptionMeta;
};

export type StreamStatus = {
  running: boolean;
  attached: boolean;
  port: number;
  url: string;
  inventoryOverlayUrl: string;
  gamePreviewUrl: string;
  metaUrl: string;
  error?: string;
  meta?: StreamMeta;
};

export type StreamMetaResult = {
  ok: boolean;
  meta?: StreamMeta;
};

export type ExodiaApi = {
  getSettings: () => Promise<SettingsResult>;
  setSettings: (partial: Partial<ExodiaSettings>) => Promise<SettingsResult>;
  spawnSmokeTest: () => Promise<SmokeTestResult>;
  quit: () => Promise<void>;
  onLogLine: (callback: (payload: LogLinePayload) => void) => () => void;
  selectScriptsFolder: () => Promise<SelectFolderResult>;
  listDirectory: (dirPath: string, options?: ListDirectoryOptions) => Promise<ListDirectoryResult>;
  readTextFile: (filePath: string) => Promise<ReadTextFileResult>;
  refreshDebugFrame: (mode?: DebugFrameMode) => Promise<DebugFrameResult>;
  saveDebugSnapshot: (imageDataUrl: string, defaultName?: string) => Promise<SaveSnapshotResult>;
  openLogsFolder: () => Promise<void>;
  runCalibrateClientRect: () => Promise<CalibrateClientRectResult>;
  listBots: () => Promise<BotManifestEntry[]>;
  getBotRun: () => Promise<BotRunInfo | null>;
  startBot: (request: StartBotRequest) => Promise<StartBotResult>;
  stopBot: () => Promise<StopBotResult>;
  sendBotRuntimeCommand: (command: string) => Promise<RuntimeCommandResult>;
  onBotRunUpdate: (callback: (run: BotRunInfo | null) => void) => () => void;
  onBotStatusUpdate: (callback: (status: RuntimeStatusPayload | null) => void) => () => void;
  fetchGamePreview: () => Promise<GamePreviewResult>;
  fetchInventoryOverlay: () => Promise<GamePreviewResult>;
  fetchPristineClient: () => Promise<GamePreviewResult>;
  getStreamStatus: () => Promise<StreamStatus>;
  startStream: () => Promise<StreamStatus>;
  stopStream: () => Promise<StreamStatus>;
  invalidateStreamCache: () => Promise<void>;
  restartStream: () => Promise<StreamStatus>;
  onStreamStatusUpdate: (callback: (status: StreamStatus) => void) => () => void;
  fetchStreamMeta: () => Promise<StreamMetaResult>;
  listActionBlocks: () => Promise<ActionBlockDef[]>;
  runSingleAction: (request: RunSingleActionRequest) => Promise<RunSingleActionResult>;
  selectTemplateFile: () => Promise<SelectTemplateFileResult>;
  listItemCatalog: () => Promise<ItemCatalogListResult>;
  resolveTemplateItem: (imagePath: string) => Promise<ResolveTemplateItemResult>;
  saveTemplate: (request: SaveTemplateRequest) => Promise<SaveTemplateResult>;
};

export type {
  BotManifestEntry,
  BotRunInfo,
  RuntimeStatusPayload,
  StartBotRequest,
  StartBotResult,
  StopBotResult,
  RuntimeCommandResult,
} from './bots';

declare global {
  interface Window {
    exodia: ExodiaApi;
  }
}

export {};
