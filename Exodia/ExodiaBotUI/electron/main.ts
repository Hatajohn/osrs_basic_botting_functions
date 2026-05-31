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
  type TemplateWatchlist,
} from '../shared/ipc';
import { listActionBlocks, runSingleAction } from './actionRunner';
import { refreshDebugFrame, saveDebugFrameSnapshot } from './debugFrame';
import { runCalibrateClientRect } from './calibrateClientRect';
import { listDirectory, readTextFile } from './files';
import { listItemCatalog, resolveTemplateItem } from './itemCatalog';
import { saveTemplate } from './saveTemplate';
import { selectTemplateFile } from './templateFile';
import { loadTemplateWatchlist, saveTemplateWatchlist, syncWatchlistToControlFile } from './templateWatchlist';
import { loadBotsManifest } from './manifestLoader';
import { fetchGamePreview, fetchInventoryOverlay, fetchPristineClient } from './previewClient';
import { StreamProcessManager, waitForStreamHealthy } from './streamManager';
import { ProcessManager } from './processManager';
import { pythonExists } from './paths';
import {
  getConfigFilePath,
  loadSettings,
  resolveSettings,
  saveSettings,
  type ExodiaSettings,
} from './settings';
import {
  attachWindowStatePersistence,
  loadWindowState,
  windowOptionsFromState,
} from './windowState';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// WSL / headless Linux often fails GPU init and shows a blank window.
if (process.platform === 'linux') {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch('disable-gpu');
}

let mainWindow: BrowserWindow | null = null;
let processManager: ProcessManager | null = null;
let streamManager: StreamProcessManager | null = null;
let actionRunning = false;

function botRunBlocksAction(): boolean {
  const run = processManager?.getActiveRun();
  if (!run) return false;
  return run.state !== 'idle';
}

function emitLog(line: string, stream: LogLinePayload['stream'] = 'system'): void {
  const payload: LogLinePayload = { line, stream, ts: Date.now() };
  mainWindow?.webContents.send(IPC.LOG_LINE, payload);
}

function createWindow(): void {
  const savedState = loadWindowState();

  mainWindow = new BrowserWindow({
    ...windowOptionsFromState(savedState),
    title: 'Exodia',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (savedState.isMaximized) {
    mainWindow.maximize();
  }

  attachWindowStatePersistence(mainWindow);

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

  ipcMain.handle(IPC.LIST_DIRECTORY, (_event, dirPath: string, options?: { markdownOnly?: boolean }) =>
    listDirectory(dirPath, options),
  );

  ipcMain.handle(IPC.READ_TEXT_FILE, (_event, filePath: string) => readTextFile(filePath));

  ipcMain.handle(IPC.SELECT_TEMPLATE_FILE, async () =>
    selectTemplateFile(mainWindow),
  );

  ipcMain.handle(IPC.LIST_ITEM_CATALOG, () => listItemCatalog());

  ipcMain.handle(IPC.RESOLVE_TEMPLATE_ITEM, (_event, imagePath: string) =>
    resolveTemplateItem(imagePath),
  );

  ipcMain.handle(IPC.SAVE_TEMPLATE, async (_event, request) => {
    emitLog(`Save template (${request.mode})…`, 'system');
    const result = await saveTemplate(request);
    if (result.ok) {
      emitLog(
        `Saved ${result.templateFile ?? 'template'} → ${result.dest ?? '?'}/ (${result.itemId ?? ''})`,
        'system',
      );
    } else {
      emitLog(`Save template failed: ${result.error ?? 'unknown'}`, 'stderr');
    }
    return result;
  });

  ipcMain.handle(
    IPC.REFRESH_DEBUG_FRAME,
    async (_event, mode?: DebugFrameMode, options?: import('../shared/ipc').DebugFrameOptions) => {
    const frameMode = mode ?? 'inventory_identify';
    emitLog(`Debug frame refresh (${frameMode})…`, 'system');
    const result = await refreshDebugFrame(frameMode, options);
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
    if (streamManager) {
      await streamManager.stopForCalibration();
      mainWindow?.webContents.send(
        IPC.STREAM_STATUS_UPDATE,
        await streamManager.getStatus(),
      );
    }
    const result = await runCalibrateClientRect((line, stream) => emitLog(line, stream));
    if (result.canceled) {
      emitLog('Calibration cancelled.', 'system');
    } else if (result.ok) {
      emitLog('Client rect calibration saved.', 'system');
      if (streamManager) {
        const status = await streamManager.restart();
        mainWindow?.webContents.send(IPC.STREAM_STATUS_UPDATE, status);
        if (status.running) {
          emitLog(
            status.attached
              ? `Attached to perception stream on port ${status.port}`
              : `Perception stream live on port ${status.port}`,
            'system',
          );
        } else if (status.error) {
          emitLog(`Perception stream failed to start: ${status.error}`, 'stderr');
        }
      }
    } else if (result.error) {
      emitLog(result.error, 'stderr');
    }
    return result;
  });

  ipcMain.handle(IPC.LIST_BOTS, () => {
    try {
      return loadBotsManifest().bots;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      emitLog(message, 'stderr');
      return [];
    }
  });

  ipcMain.handle(IPC.GET_BOT_RUN, () => processManager?.getActiveRun() ?? null);

  ipcMain.handle(IPC.START_BOT, async (_event, request: { botId?: string; specPaths?: string[]; argValues?: Record<string, number | string | boolean> }) => {
    if (!processManager) return { ok: false, error: 'Process manager not ready' };
    if (actionRunning) {
      const error = 'Cannot start bot: an action is still running';
      emitLog(error, 'stderr');
      return { ok: false, error };
    }
    return processManager.startBot(request.botId, request.argValues, request.specPaths);
  });

  ipcMain.handle(IPC.LIST_ACTION_BLOCKS, () => listActionBlocks());

  ipcMain.handle(
    IPC.RUN_SINGLE_ACTION,
    async (_event, request: { blockId: string; args?: Record<string, string>; dryRun?: boolean }) => {
      if (actionRunning) {
        const error = 'Another action is already running';
        emitLog(error, 'stderr');
        return { ok: false, blockId: request?.blockId ?? '', error };
      }
      if (botRunBlocksAction()) {
        const error = 'Cannot run action while a bot is active';
        emitLog(error, 'stderr');
        return { ok: false, blockId: request?.blockId ?? '', error };
      }
      actionRunning = true;
      const settings = loadSettings();
      const blockId = request?.blockId ?? '';
      const templateAction =
        blockId === 'click_template_world' || blockId === 'click_template_inv';
      let seqBefore = 0;
      let port = settings.streamPort ?? 8765;
      if (streamManager) {
        const stBefore = await streamManager.getStatus();
        seqBefore = stBefore.meta?.capture_seq ?? 0;
        port = stBefore.port;
      }
      try {
        return await runSingleAction(
          request,
          (line, stream) => emitLog(line, stream),
          () => processManager?.getActiveRun() ?? null,
        );
      } finally {
        actionRunning = false;
        if (streamManager) {
          const st = await streamManager.getStatus();
          if (templateAction) {
            const advanced = await streamManager.waitForCaptureSeqAdvance(port, seqBefore, 2000);
            if (!advanced) {
              emitLog('Stream capture_seq frozen after action — hard-resetting…', 'system');
              const restarted = await streamManager.restart();
              mainWindow?.webContents.send(IPC.STREAM_STATUS_UPDATE, restarted);
            }
          } else if (!st.running) {
            emitLog('Perception stream offline after action — restarting…', 'system');
            const restarted = await streamManager.restart();
            mainWindow?.webContents.send(IPC.STREAM_STATUS_UPDATE, restarted);
          }
        }
      }
    },
  );

  ipcMain.handle(IPC.STOP_BOT, async () => {
    if (!processManager) return { ok: false, error: 'Process manager not ready' };
    return processManager.stopBot();
  });

  ipcMain.handle(IPC.BOT_RUNTIME_CMD, async (_event, command: string) => {
    if (!processManager) return { ok: false, error: 'Process manager not ready' };
    return processManager.sendRuntimeCommand(command);
  });

  ipcMain.handle(IPC.FETCH_GAME_PREVIEW, async () => {
    const frame = await fetchGamePreview();
    if (!frame) return { ok: false };
    return { ok: true, imageDataUrl: frame.imageDataUrl, fetchedAt: frame.fetchedAt };
  });

  ipcMain.handle(IPC.FETCH_INVENTORY_OVERLAY, async () => {
    const frame = await fetchInventoryOverlay();
    if (!frame) return { ok: false };
    return { ok: true, imageDataUrl: frame.imageDataUrl, fetchedAt: frame.fetchedAt };
  });

  ipcMain.handle(IPC.FETCH_PRISTINE_CLIENT, async () => {
    const frame = await fetchPristineClient();
    if (!frame) return { ok: false };
    return { ok: true, imageDataUrl: frame.imageDataUrl, fetchedAt: frame.fetchedAt };
  });

  ipcMain.handle(IPC.GET_STREAM_STATUS, async () => {
    if (!streamManager) return { running: false, attached: false, port: 8765, url: '', inventoryOverlayUrl: '', gamePreviewUrl: '', metaUrl: '' };
    return streamManager.getStatus();
  });

  ipcMain.handle(IPC.START_STREAM, async () => {
    if (!streamManager) {
      return { running: false, attached: false, port: 8765, url: '', inventoryOverlayUrl: '', gamePreviewUrl: '', metaUrl: '', error: 'Stream manager not ready' };
    }
    return streamManager.start();
  });

  ipcMain.handle(IPC.STOP_STREAM, async () => {
    if (!streamManager) {
      return { running: false, attached: false, port: 8765, url: '', inventoryOverlayUrl: '', gamePreviewUrl: '', metaUrl: '' };
    }
    await streamManager.stop();
    return streamManager.getStatus();
  });

  ipcMain.handle(IPC.INVALIDATE_STREAM_CACHE, async () => {
    streamManager?.invalidateCache();
  });

  ipcMain.handle(IPC.RESTART_STREAM, async () => {
    if (!streamManager) {
      return { running: false, attached: false, port: 8765, url: '', inventoryOverlayUrl: '', gamePreviewUrl: '', metaUrl: '', error: 'Stream manager not ready' };
    }
    const status = await streamManager.restart();
    mainWindow?.webContents.send(IPC.STREAM_STATUS_UPDATE, status);
    return status;
  });

  ipcMain.handle(IPC.FETCH_STREAM_META, async () => {
    if (!streamManager) return { ok: false };
    const status = await streamManager.getStatus();
    if (!status.running || !status.meta) return { ok: false };
    return { ok: true, meta: status.meta };
  });

  ipcMain.handle(IPC.GET_TEMPLATE_WATCHLIST, () => loadTemplateWatchlist());

  ipcMain.handle(IPC.SET_TEMPLATE_WATCHLIST, (_event, watchlist: TemplateWatchlist) => {
    const saved = saveTemplateWatchlist(watchlist);
    streamManager?.syncWatchlistControl();
    return saved;
  });
}

app.whenReady().then(() => {
  registerIpc();
  createWindow();

  streamManager = new StreamProcessManager((line, stream) => emitLog(line, stream));

  processManager = new ProcessManager(
    (line, stream) => emitLog(line, stream),
    {
      onRunUpdate: (run) => {
        mainWindow?.webContents.send(IPC.BOT_RUN_UPDATE, run);
      },
      onStatusUpdate: (status) => {
        mainWindow?.webContents.send(IPC.BOT_STATUS_UPDATE, status);
      },
    },
    {
      ensureStreamForBot: async () => {
        if (!streamManager) {
          return { ok: false, error: 'perception stream required' };
        }
        let status = await streamManager.getStatus();
        if (!status.running) {
          status = await streamManager.start();
        }
        if (!status.running) {
          return {
            ok: false,
            error: status.error ?? 'perception stream required',
          };
        }
        const health = await waitForStreamHealthy(status.port);
        if (!health.healthy) {
          return {
            ok: false,
            error: health.error ?? 'perception stream not healthy',
          };
        }
        return { ok: true };
      },
    },
  );

  try {
    const { resolvedExodiaRoot } = resolveSettings(loadSettings());
    syncWatchlistToControlFile(resolvedExodiaRoot);
  } catch {
    // settings may be incomplete on first launch
  }

  void streamManager.start().then((status) => {
    if (status.running) {
      emitLog(
        status.attached
          ? `Attached to existing stream on port ${status.port}`
          : `Perception stream live on port ${status.port}`,
        'system',
      );
    } else if (status.error) {
      emitLog(`Perception stream not started: ${status.error}`, 'system');
    }
  });

  emitLog('Exodia desktop ready.', 'system');

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  processManager?.dispose();
  processManager = null;
  streamManager?.dispose();
  streamManager = null;
  if (process.platform !== 'darwin') app.quit();
});

export function showAboutDialog(): void {
  const resolved = resolveSettings(loadSettings());
  dialog.showMessageBox({
    type: 'info',
    title: 'About Exodia',
    message: 'Exodia Desktop',
    detail: [
      'Version 0.2.0 (Phase 2)',
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
