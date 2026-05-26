import { contextBridge, ipcRenderer } from 'electron';
import { IPC, type ExodiaApi, type LogLinePayload } from '../shared/ipc';

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
};

contextBridge.exposeInMainWorld('exodia', api);
