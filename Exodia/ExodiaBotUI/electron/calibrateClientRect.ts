import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import type { CalibrateClientRectResult } from '../shared/ipc';
import { pythonExists } from './paths';
import { loadSettings, resolveSettings } from './settings';

const SCRIPT_NAME = 'calibrate_client_rect.py';

type LogSink = (line: string, stream: 'stdout' | 'stderr') => void;

function pipeLines(chunk: string, stream: 'stdout' | 'stderr', sink: LogSink): void {
  chunk.split(/\r?\n/).filter(Boolean).forEach((line) => sink(line, stream));
}

export async function runCalibrateClientRect(sink: LogSink): Promise<CalibrateClientRectResult> {
  const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
  const scriptPath = path.join(resolvedExodiaRoot, SCRIPT_NAME);

  if (!pythonExists(resolvedPythonPath)) {
    const error = `Python not found at: ${resolvedPythonPath}`;
    sink(error, 'stderr');
    return { ok: false, stdout: '', stderr: error, exitCode: null, error };
  }
  if (!fs.existsSync(scriptPath)) {
    const error = `Calibration script not found: ${scriptPath}`;
    sink(error, 'stderr');
    return { ok: false, stdout: '', stderr: error, exitCode: null, error };
  }

  sink(`Running ${SCRIPT_NAME}…`, 'stdout');

  return new Promise((resolve) => {
    const child = spawn(resolvedPythonPath, [scriptPath], {
      cwd: resolvedExodiaRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        EXODIA_ROOT: resolvedExodiaRoot,
        DISPLAY: process.env.DISPLAY ?? ':0',
      },
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk: Buffer) => {
      const text = chunk.toString();
      stdout += text;
      pipeLines(text, 'stdout', sink);
    });

    child.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString();
      stderr += text;
      pipeLines(text, 'stderr', sink);
    });

    child.on('error', (err) => {
      const message = err.message;
      sink(message, 'stderr');
      resolve({ ok: false, stdout, stderr: message, exitCode: null, error: message });
    });

    child.on('close', (code) => {
      const trimmedOut = stdout.trim();
      const trimmedErr = stderr.trim();
      const canceled =
        trimmedOut.includes('Calibration cancelled') ||
        trimmedOut.includes('Calibration cancelled (empty selection)');

      if (canceled) {
        resolve({
          ok: false,
          stdout: trimmedOut,
          stderr: trimmedErr,
          exitCode: code,
          canceled: true,
        });
        return;
      }

      const ok = code === 0;
      resolve({
        ok,
        stdout: trimmedOut,
        stderr: trimmedErr,
        exitCode: code,
        error: ok ? undefined : trimmedErr || `Calibration exited with code ${code ?? 'unknown'}`,
      });
    });
  });
}
