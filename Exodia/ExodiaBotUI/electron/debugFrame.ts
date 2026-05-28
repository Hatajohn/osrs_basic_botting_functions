import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { dialog } from 'electron';
import type { DebugFrameMode, DebugFrameOptions, DebugFrameResult } from '../shared/ipc';
import { pythonExists } from './paths';
import { loadSettings, resolveSettings } from './settings';

const SCRIPT_NAME = 'exodia_debug_frame.py';

function parseJsonLine(stdout: string): Record<string, unknown> | null {
  const lines = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      return JSON.parse(lines[i]) as Record<string, unknown>;
    } catch {
      continue;
    }
  }
  return null;
}

function readImageDataUrl(imagePath: string): string | undefined {
  if (!fs.existsSync(imagePath)) return undefined;
  const buf = fs.readFileSync(imagePath);
  return `data:image/png;base64,${buf.toString('base64')}`;
}

export async function refreshDebugFrame(
  mode: DebugFrameMode,
  options?: DebugFrameOptions,
): Promise<DebugFrameResult> {
  const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
  const scriptPath = path.join(resolvedExodiaRoot, SCRIPT_NAME);

  if (!pythonExists(resolvedPythonPath)) {
    return {
      ok: false,
      mode,
      error: `Python not found at: ${resolvedPythonPath}`,
    };
  }
  if (!fs.existsSync(scriptPath)) {
    return {
      ok: false,
      mode,
      error: `Debug frame script not found: ${scriptPath}`,
    };
  }

  return new Promise((resolve) => {
    const settings = loadSettings();
    const psExe = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
    const useWslPs = process.platform === 'linux' && fs.existsSync(psExe);
    const maxWidth =
      options?.maxWidth !== undefined ? options.maxWidth : (settings.streamMaxWidth ?? 640);
    const argv = [scriptPath, '--mode', mode, '--force-sync', '--max-width', String(maxWidth)];
    const child = spawn(resolvedPythonPath, argv, {
      cwd: resolvedExodiaRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        EXODIA_ROOT: resolvedExodiaRoot,
        EXODIA_STREAM_PORT: String(settings.streamPort ?? 8765),
        EXODIA_CAPTURE_STREAM: '1',
        EXODIA_DEBUG_FRAME_MAX_WIDTH: String(maxWidth),
        ...(useWslPs
          ? {
              EXODIA_CAPTURE_BACKEND: process.env.EXODIA_CAPTURE_BACKEND ?? 'wsl_ps',
              EXODIA_INPUT_BACKEND: process.env.EXODIA_INPUT_BACKEND ?? 'wsl_ps',
            }
          : {}),
      },
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    child.on('error', (err) => {
      resolve({ ok: false, mode, error: err.message, stderr: stderr.trim() });
    });

    child.on('close', (code) => {
      const parsed = parseJsonLine(stdout);
      if (!parsed) {
        resolve({
          ok: false,
          mode,
          error: stderr.trim() || `Debug frame exited with code ${code ?? 'unknown'}`,
          stderr: stderr.trim(),
          stdout: stdout.trim(),
        });
        return;
      }

      const ok = Boolean(parsed.ok);
      const imagePath = typeof parsed.path === 'string' ? parsed.path : undefined;
      const result: DebugFrameResult = {
        ok,
        mode: (typeof parsed.mode === 'string' ? parsed.mode : mode) as DebugFrameMode,
        path: imagePath,
        imageDataUrl: imagePath ? readImageDataUrl(imagePath) : undefined,
        occupied: typeof parsed.occupied === 'number' ? parsed.occupied : undefined,
        unknown: typeof parsed.unknown === 'number' ? parsed.unknown : undefined,
        tmpCount: typeof parsed.tmp_count === 'number' ? parsed.tmp_count : undefined,
        width: typeof parsed.width === 'number' ? parsed.width : undefined,
        height: typeof parsed.height === 'number' ? parsed.height : undefined,
        sourceWidth: typeof parsed.source_width === 'number' ? parsed.source_width : undefined,
        sourceHeight: typeof parsed.source_height === 'number' ? parsed.source_height : undefined,
        scaled: typeof parsed.scaled === 'boolean' ? parsed.scaled : undefined,
        error: typeof parsed.error === 'string' ? parsed.error : undefined,
        hint: typeof parsed.hint === 'string' ? parsed.hint : undefined,
        refreshedAt: Date.now(),
        stderr: stderr.trim() || undefined,
      };

      if (!ok && !result.error) {
        result.error = stderr.trim() || `Debug frame exited with code ${code ?? 'unknown'}`;
      }

      resolve(result);
    });
  });
}

export async function saveDebugFrameSnapshot(
  imageDataUrl: string,
  defaultName?: string,
): Promise<{ ok: boolean; path?: string; canceled?: boolean; error?: string }> {
  const match = /^data:image\/png;base64,(.+)$/.exec(imageDataUrl);
  if (!match) {
    return { ok: false, error: 'Invalid image data' };
  }

  const { resolvedExodiaRoot } = resolveSettings(loadSettings());
  const capturesDir = path.join(resolvedExodiaRoot, 'captures');
  fs.mkdirSync(capturesDir, { recursive: true });

  const result = await dialog.showSaveDialog({
    title: 'Save RuneLite snapshot',
    defaultPath: path.join(capturesDir, defaultName ?? `runelite_snapshot_${Date.now()}.png`),
    filters: [{ name: 'PNG image', extensions: ['png'] }],
  });

  if (result.canceled || !result.filePath) {
    return { ok: false, canceled: true };
  }

  try {
    fs.writeFileSync(result.filePath, Buffer.from(match[1], 'base64'));
    return { ok: true, path: result.filePath };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, error: message };
  }
}
