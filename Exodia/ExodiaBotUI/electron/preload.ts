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
  listDirectory: (dirPath) => ipcRenderer.invoke(IPC.LIST_DIRECTORY, dirPath),
  refreshDebugFrame: (mode) => ipcRenderer.invoke(IPC.REFRESH_DEBUG_FRAME, mode),
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
};

contextBridge.exposeInMainWorld('exodia', api);
