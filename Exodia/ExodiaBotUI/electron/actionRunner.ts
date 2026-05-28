import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import type { ActionBlockDef, RunSingleActionRequest, RunSingleActionResult } from '../shared/ipc';
import { attachClickPreview } from './actionPreview';
import { pythonExists } from './paths';
import { loadSettings, resolveSettings } from './settings';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SCRIPT_NAME = 'exodia_chain.py';
const MANIFEST_NAME = 'actions.manifest.json';

type LogSink = (line: string, stream: 'stdout' | 'stderr' | 'system') => void;

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

function pipeLines(
  chunk: string,
  stream: 'stdout' | 'stderr',
  sink: LogSink,
  prefix: string,
): void {
  chunk.split(/\r?\n/).filter(Boolean).forEach((line) => {
    sink(`${prefix}${line}`, stream);
  });
}

function manifestPath(): string {
  return path.join(__dirname, '..', MANIFEST_NAME);
}

export function listActionBlocks(): ActionBlockDef[] {
  const p = manifestPath();
  if (!fs.existsSync(p)) return [];
  try {
    const data = JSON.parse(fs.readFileSync(p, 'utf8')) as { blocks?: ActionBlockDef[] };
    return Array.isArray(data.blocks) ? data.blocks : [];
  } catch {
    return [];
  }
}

function botIsActive(
  getRun: () => { state: string } | null,
): boolean {
  const run = getRun();
  if (!run) return false;
  return run.state !== 'idle';
}

export async function runSingleAction(
  request: RunSingleActionRequest,
  sink: LogSink,
  getBotRun: () => { state: string } | null,
): Promise<RunSingleActionResult> {
  const blockId = request.blockId?.trim();
  if (!blockId) {
    return { ok: false, blockId: '', error: 'Missing block id' };
  }

  if (botIsActive(getBotRun)) {
    const error = 'Cannot run action while a bot is active';
    sink(error, 'stderr');
    return { ok: false, blockId, error };
  }

  const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
  const scriptPath = path.join(resolvedExodiaRoot, SCRIPT_NAME);

  if (!pythonExists(resolvedPythonPath)) {
    const error = `Python not found at: ${resolvedPythonPath}`;
    sink(error, 'stderr');
    return { ok: false, blockId, error };
  }
  if (!fs.existsSync(scriptPath)) {
    const error = `Chain script not found: ${scriptPath}`;
    sink(error, 'stderr');
    return { ok: false, blockId, error };
  }

  const args = request.args ?? {};
  const argv = [
    scriptPath,
    'single',
    '--block',
    blockId,
    '--args',
    JSON.stringify(args),
  ];
  if (request.dryRun) {
    argv.push('--dry-run');
  }

  sink(`action ${blockId}…`, 'system');

  return new Promise((resolve) => {
    const psExe = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
    const useWslPs = process.platform === 'linux' && fs.existsSync(psExe);
    const child = spawn(resolvedPythonPath, argv, {
      cwd: resolvedExodiaRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        EXODIA_ROOT: resolvedExodiaRoot,
        EXODIA_STREAM_PORT: String(loadSettings().streamPort ?? 8765),
        EXODIA_CAPTURE_STREAM: '1',
        EXODIA_MASK_PANELS: '0',
        EXODIA_DEBUG_FRAME_MAX_WIDTH: String(loadSettings().streamMaxWidth ?? 640),
        EXO_SHAPE_THR: process.env.EXO_SHAPE_THR ?? '0.52',
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
      const text = chunk.toString();
      stdout += text;
      pipeLines(text, 'stdout', sink, '');
    });
    child.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString();
      stderr += text;
      pipeLines(text, 'stderr', sink, '');
    });

    child.on('error', (err) => {
      const error = err.message;
      sink(error, 'stderr');
      resolve({ ok: false, blockId, error, stderr: stderr.trim() });
    });

    child.on('close', (code) => {
      const parsed = parseJsonLine(stdout);
      if (!parsed) {
        const error = stderr.trim() || `Action exited with code ${code ?? 'unknown'}`;
        sink(`action ${blockId} failed: ${error}`, 'stderr');
        resolve({ ok: false, blockId, error, stderr: stderr.trim(), stdout: stdout.trim() });
        return;
      }

      const ok = Boolean(parsed.ok);
      const durationMs =
        typeof parsed.duration_ms === 'number' ? parsed.duration_ms : undefined;
      const inner = parsed.result as Record<string, unknown> | undefined;
      const error =
        typeof parsed.error === 'string'
          ? parsed.error
          : typeof inner?.error === 'string'
            ? inner.error
            : undefined;

      if (ok) {
        sink(`action ${blockId} ok${durationMs != null ? ` (${durationMs}ms)` : ''}`, 'system');
      } else {
        sink(`action ${blockId} failed: ${error ?? 'unknown'}`, 'stderr');
      }

      if (inner && typeof inner.capture_seq === 'number') {
        const captureSeq = inner.capture_seq;
        const frameAgeMs =
          typeof inner.frame_age_ms === 'number' ? inner.frame_age_ms : undefined;
        const source = typeof inner.source === 'string' ? inner.source : undefined;
        const perceptionSource =
          typeof inner.perception_source === 'string' ? inner.perception_source : undefined;
        sink(
          `frame seq=${captureSeq} age=${frameAgeMs ?? '?'}ms source=${source || perceptionSource || '?'}`,
          'system',
        );
      }

      resolve(
        attachClickPreview(blockId, {
          ok,
          blockId,
          durationMs,
          error,
          result: inner,
          stderr: stderr.trim() || undefined,
          stdout: stdout.trim() || undefined,
        }),
      );
    });
  });
}
