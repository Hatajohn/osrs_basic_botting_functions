import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  BrowserWindow,
  app,
  dialog,
  ipcMain,
  shell,
} from 'electron';
import {
  IPC,
  type DebugFrameMode,
  type LogLinePayload,
  type SmokeTestResult,
} from '../shared/ipc';
import { refreshDebugFrame, saveDebugFrameSnapshot } from './debugFrame';
import { runCalibrateClientRect } from './calibrateClientRect';
import { listDirectory } from './files';
import { pythonExists } from './paths';
import {
  getConfigFilePath,
  loadSettings,
  resolveSettings,
  saveSettings,
  type ExodiaSettings,
} from './settings';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// WSL / headless Linux often fails GPU init and shows a blank window.
if (process.platform === 'linux') {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch('disable-gpu');
}

let mainWindow: BrowserWindow | null = null;

function emitLog(line: string, stream: LogLinePayload['stream'] = 'system'): void {
  const payload: LogLinePayload = { line, stream, ts: Date.now() };
  mainWindow?.webContents.send(IPC.LOG_LINE, payload);
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'Exodia',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    if (process.env.EXODIA_DEVTOOLS === '1') {
      mainWindow.webContents.openDevTools({ mode: 'detach' });
    }
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
    console.error(`Failed to load ${url}: ${description} (${code})`);
  });

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('Renderer process gone:', details);
  });

  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      console.error(`[renderer ${level}] ${message} (${sourceId}:${line})`);
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function settingsPayload() {
  const settings = loadSettings();
  const resolved = resolveSettings(settings);
  return {
    settings,
    resolved: {
      exodiaRoot: resolved.resolvedExodiaRoot,
      pythonPath: resolved.resolvedPythonPath,
      logsDir: resolved.resolvedLogsDir,
      chainsDir: resolved.resolvedChainsDir,
      scriptsFolder: resolved.resolvedScriptsFolder,
    },
  };
}

function registerIpc(): void {
  ipcMain.handle(IPC.GET_SETTINGS, () => settingsPayload());

  ipcMain.handle(IPC.SET_SETTINGS, (_event, partial: Partial<ExodiaSettings>) => {
    saveSettings(partial);
    return settingsPayload();
  });

  ipcMain.handle(IPC.APP_QUIT, () => {
    app.quit();
  });

  ipcMain.handle(IPC.SPAWN_SMOKE_TEST, async (): Promise<SmokeTestResult> => {
    const { resolvedPythonPath } = resolveSettings(loadSettings());

    if (!pythonExists(resolvedPythonPath)) {
      const error = `Python not found at: ${resolvedPythonPath}`;
      emitLog(error, 'stderr');
      return { ok: false, stdout: '', stderr: error, exitCode: null, error };
    }

    emitLog(`Smoke test: ${resolvedPythonPath} -c "print('ok')"`, 'system');

    return new Promise((resolve) => {
      const child = spawn(resolvedPythonPath, ['-c', "print('ok')"], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';

      child.stdout.on('data', (chunk: Buffer) => {
        const text = chunk.toString();
        stdout += text;
        text.split(/\r?\n/).filter(Boolean).forEach((line) => emitLog(line, 'stdout'));
      });

      child.stderr.on('data', (chunk: Buffer) => {
        const text = chunk.toString();
        stderr += text;
        text.split(/\r?\n/).filter(Boolean).forEach((line) => emitLog(line, 'stderr'));
      });

      child.on('error', (err) => {
        const message = err.message;
        emitLog(message, 'stderr');
        resolve({ ok: false, stdout, stderr: message, exitCode: null, error: message });
      });

      child.on('close', (code) => {
        const ok = code === 0 && stdout.trim() === 'ok';
        if (!ok && code !== 0) {
          emitLog(`Smoke test exited with code ${code}`, 'stderr');
        }
        resolve({ ok, stdout: stdout.trim(), stderr: stderr.trim(), exitCode: code });
      });
    });
  });

  ipcMain.handle(IPC.SELECT_SCRIPTS_FOLDER, async () => {
    const { resolvedScriptsFolder } = resolveSettings(loadSettings());
    const result = await dialog.showOpenDialog(mainWindow!, {
      title: 'Select scripts folder',
      defaultPath: resolvedScriptsFolder,
      properties: ['openDirectory'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { canceled: true };
    }
    const folder = result.filePaths[0];
    saveSettings({ scriptsFolder: folder });
    return { canceled: false, path: folder };
  });

  ipcMain.handle(IPC.LIST_DIRECTORY, (_event, dirPath: string) => listDirectory(dirPath));

  ipcMain.handle(IPC.REFRESH_DEBUG_FRAME, async (_event, mode?: DebugFrameMode) => {
    const frameMode = mode ?? 'inventory_identify';
    emitLog(`Debug frame refresh (${frameMode})…`, 'system');
    const result = await refreshDebugFrame(frameMode);
    if (result.ok) {
      const stats = [
        result.occupied != null ? `occupied=${result.occupied}` : null,
        result.unknown != null ? `unknown=${result.unknown}` : null,
        result.tmpCount != null ? `tmp=${result.tmpCount}` : null,
      ]
        .filter(Boolean)
        .join(' ');
      emitLog(`Debug frame OK${stats ? `: ${stats}` : ''}`, 'system');
    } else {
      const msg = result.hint ? `${result.error} — ${result.hint}` : result.error ?? 'refresh failed';
      emitLog(msg, 'stderr');
    }
    return result;
  });

  ipcMain.handle(
    IPC.SAVE_DEBUG_SNAPSHOT,
    (_event, imageDataUrl: string, defaultName?: string) =>
      saveDebugFrameSnapshot(imageDataUrl, defaultName),
  );

  ipcMain.handle(IPC.OPEN_LOGS_FOLDER, () => {
    revealLogsFolder();
  });

  ipcMain.handle(IPC.RUN_CALIBRATE_CLIENT_RECT, async () => {
    emitLog('Starting client rect calibration…', 'system');
    const result = await runCalibrateClientRect((line, stream) => emitLog(line, stream));
    if (result.canceled) {
      emitLog('Calibration cancelled.', 'system');
    } else if (result.ok) {
      emitLog('Client rect calibration saved.', 'system');
    } else if (result.error) {
      emitLog(result.error, 'stderr');
    }
    return result;
  });
}

app.whenReady().then(() => {
  registerIpc();
  createWindow();
  emitLog('Exodia desktop ready.', 'system');

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

export function showAboutDialog(): void {
  const resolved = resolveSettings(loadSettings());
  dialog.showMessageBox({
    type: 'info',
    title: 'About Exodia',
    message: 'Exodia Desktop',
    detail: [
      'Version 0.1.0 (Phase 1)',
      '',
      `Exodia root: ${resolved.resolvedExodiaRoot}`,
      `Python: ${resolved.resolvedPythonPath}`,
      `Config: ${getConfigFilePath()}`,
    ].join('\n'),
  });
}

export function revealLogsFolder(): void {
  const { resolvedLogsDir } = resolveSettings(loadSettings());
  shell.openPath(resolvedLogsDir);
}
