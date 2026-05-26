import { spawn } from 'node:child_process';
import path from 'node:path';
import { pythonExists } from './paths';
import { loadSettings, resolveSettings } from './settings';

const SCRIPT_NAME = 'exodia_ctl.py';

export type RuntimeSendResult = {
  ok: boolean;
  stdout: string;
  stderr: string;
  exitCode: number | null;
  error?: string;
};

export async function sendRuntimeCommand(
  command: string,
  allowedCommands: string[],
  args?: Record<string, unknown>,
): Promise<RuntimeSendResult> {
  const cmd = command.trim().toLowerCase();
  if (!allowedCommands.map((c) => c.toLowerCase()).includes(cmd)) {
    return {
      ok: false,
      stdout: '',
      stderr: '',
      exitCode: null,
      error: `Command "${command}" is not allowed for the active bot`,
    };
  }

  const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
  const scriptPath = path.join(resolvedExodiaRoot, SCRIPT_NAME);

  if (!pythonExists(resolvedPythonPath)) {
    const error = `Python not found at: ${resolvedPythonPath}`;
    return { ok: false, stdout: '', stderr: error, exitCode: null, error };
  }

  const spawnArgs = [scriptPath, cmd];
  if (args && Object.keys(args).length > 0) {
    spawnArgs.push('--args', JSON.stringify(args));
  }

  return new Promise((resolve) => {
    const child = spawn(resolvedPythonPath, spawnArgs, {
      cwd: resolvedExodiaRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        EXODIA_ROOT: resolvedExodiaRoot,
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
      resolve({
        ok: false,
        stdout,
        stderr: err.message,
        exitCode: null,
        error: err.message,
      });
    });

    child.on('close', (code) => {
      const ok = code === 0;
      resolve({
        ok,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
        exitCode: code,
        error: ok ? undefined : stderr.trim() || `exodia_ctl exited with code ${code ?? 'unknown'}`,
      });
    });
  });
}

/** Wait for runtime stop to take effect (poll status or timeout). */
export async function waitForRuntimeStop(
  statusPath: string,
  runtimeScriptId: string,
  timeoutMs = 8000,
): Promise<boolean> {
  const fs = await import('node:fs');
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      if (!fs.existsSync(statusPath)) {
        await sleep(200);
        continue;
      }
      const raw = fs.readFileSync(statusPath, 'utf8');
      const data = JSON.parse(raw) as { script?: string; stop_reason?: string };
      if (data.script === runtimeScriptId && data.stop_reason) {
        return true;
      }
    } catch {
      // ignore read races
    }
    await sleep(300);
  }
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
