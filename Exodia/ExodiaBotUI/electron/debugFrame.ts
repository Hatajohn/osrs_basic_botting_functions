import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { dialog } from 'electron';
import type { DebugFrameMode, DebugFrameResult } from '../shared/ipc';
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

export async function refreshDebugFrame(mode: DebugFrameMode): Promise<DebugFrameResult> {
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
    const child = spawn(resolvedPythonPath, [scriptPath, '--mode', mode], {
      cwd: resolvedExodiaRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, EXODIA_ROOT: resolvedExodiaRoot },
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
