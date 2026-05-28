import { contextBridge, ipcRenderer } from 'electron';
import {
  IPC,
  type BotRunInfo,
  type ExodiaApi,
  type LogLinePayload,
  type RuntimeStatusPayload,
} from '../shared/ipc';

const api: ExodiaApi = {
  getSettings: () => ipcRenderer.invoke(IPC.GET_SETTINGS),
  setSettings: (partial) => ipcRenderer.invoke(IPC.SET_SETTINGS, partial),
  spawnSmokeTest: () => ipcRenderer.invoke(IPC.SPAWN_SMOKE_TEST),
  quit: () => ipcRenderer.invoke(IPC.APP_QUIT),
  onLogLine: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: LogLinePayload) => {
      callback(payload);
    };
    ipcRenderer.on(IPC.LOG_LINE, listener);
    return () => ipcRenderer.removeListener(IPC.LOG_LINE, listener);
  },
  selectScriptsFolder: () => ipcRenderer.invoke(IPC.SELECT_SCRIPTS_FOLDER),
  listDirectory: (dirPath, options) => ipcRenderer.invoke(IPC.LIST_DIRECTORY, dirPath, options),
  readTextFile: (filePath) => ipcRenderer.invoke(IPC.READ_TEXT_FILE, filePath),
  refreshDebugFrame: (mode, options) => ipcRenderer.invoke(IPC.REFRESH_DEBUG_FRAME, mode, options),
  saveDebugSnapshot: (imageDataUrl, defaultName) =>
    ipcRenderer.invoke(IPC.SAVE_DEBUG_SNAPSHOT, imageDataUrl, defaultName),
  openLogsFolder: () => ipcRenderer.invoke(IPC.OPEN_LOGS_FOLDER),
  runCalibrateClientRect: () => ipcRenderer.invoke(IPC.RUN_CALIBRATE_CLIENT_RECT),
  listBots: () => ipcRenderer.invoke(IPC.LIST_BOTS),
  getBotRun: () => ipcRenderer.invoke(IPC.GET_BOT_RUN),
  startBot: (request) => ipcRenderer.invoke(IPC.START_BOT, request),
  stopBot: () => ipcRenderer.invoke(IPC.STOP_BOT),
  sendBotRuntimeCommand: (command) => ipcRenderer.invoke(IPC.BOT_RUNTIME_CMD, command),
  onBotRunUpdate: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, run: BotRunInfo | null) => {
      callback(run);
    };
    ipcRenderer.on(IPC.BOT_RUN_UPDATE, listener);
    return () => ipcRenderer.removeListener(IPC.BOT_RUN_UPDATE, listener);
  },
  onBotStatusUpdate: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, status: RuntimeStatusPayload | null) => {
      callback(status);
    };
    ipcRenderer.on(IPC.BOT_STATUS_UPDATE, listener);
    return () => ipcRenderer.removeListener(IPC.BOT_STATUS_UPDATE, listener);
  },
  fetchGamePreview: () => ipcRenderer.invoke(IPC.FETCH_GAME_PREVIEW),
  fetchInventoryOverlay: () => ipcRenderer.invoke(IPC.FETCH_INVENTORY_OVERLAY),
  fetchPristineClient: () => ipcRenderer.invoke(IPC.FETCH_PRISTINE_CLIENT),
  getStreamStatus: () => ipcRenderer.invoke(IPC.GET_STREAM_STATUS),
  startStream: () => ipcRenderer.invoke(IPC.START_STREAM),
  stopStream: () => ipcRenderer.invoke(IPC.STOP_STREAM),
  invalidateStreamCache: () => ipcRenderer.invoke(IPC.INVALIDATE_STREAM_CACHE),
  restartStream: () => ipcRenderer.invoke(IPC.RESTART_STREAM),
  onStreamStatusUpdate: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, status: import('../shared/ipc').StreamStatus) => {
      callback(status);
    };
    ipcRenderer.on(IPC.STREAM_STATUS_UPDATE, listener);
    return () => ipcRenderer.removeListener(IPC.STREAM_STATUS_UPDATE, listener);
  },
  fetchStreamMeta: () => ipcRenderer.invoke(IPC.FETCH_STREAM_META),
  listActionBlocks: () => ipcRenderer.invoke(IPC.LIST_ACTION_BLOCKS),
  runSingleAction: (request) => ipcRenderer.invoke(IPC.RUN_SINGLE_ACTION, request),
  selectTemplateFile: () => ipcRenderer.invoke(IPC.SELECT_TEMPLATE_FILE),
  listItemCatalog: () => ipcRenderer.invoke(IPC.LIST_ITEM_CATALOG),
  resolveTemplateItem: (imagePath) => ipcRenderer.invoke(IPC.RESOLVE_TEMPLATE_ITEM, imagePath),
  saveTemplate: (request) => ipcRenderer.invoke(IPC.SAVE_TEMPLATE, request),
  getTemplateWatchlist: () => ipcRenderer.invoke(IPC.GET_TEMPLATE_WATCHLIST),
  setTemplateWatchlist: (watchlist) => ipcRenderer.invoke(IPC.SET_TEMPLATE_WATCHLIST, watchlist),
};

contextBridge.exposeInMainWorld('exodia', api);
