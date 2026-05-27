import { execSync } from 'node:child_process';

/** Best-effort kill of anything listening on ``port`` (Linux/WSL). */
export function killListenersOnPort(port: number): void {
  if (process.platform === 'win32') {
    killListenersOnPortWindows(port);
    return;
  }
  tryExec(`fuser -k ${port}/tcp 2>/dev/null`);
  tryExec(`fuser -k ${port}/tcp`);
}

function killListenersOnPortWindows(port: number): void {
  try {
    const out = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' });
    const pids = new Set<number>();
    for (const line of out.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed.includes('LISTENING')) continue;
      const parts = trimmed.split(/\s+/);
      const pid = Number(parts[parts.length - 1]);
      if (Number.isFinite(pid) && pid > 0) {
        pids.add(pid);
      }
    }
    for (const pid of pids) {
      tryExec(`taskkill /F /PID ${pid}`);
    }
  } catch {
    // nothing listening
  }
}

/** Kill orphaned WSL PowerShell GDI capture loops left after SIGKILL. */
export function killOrphanCapturePowerShell(): void {
  if (process.platform === 'win32') {
    return;
  }
  tryExec(`pkill -9 -f '[\\$]line=\\$in.ReadLine'`);
}

/** Kill all perception stream Python processes (stream service + zombies). */
export function killPerceptionStreamProcesses(port?: number): void {
  if (process.platform === 'win32') {
    tryExec('taskkill /F /IM python.exe /FI "WINDOWTITLE eq exodia_perception*"');
    return;
  }
  tryExec(`pkill -9 -f '[e]xodia_perception_stream.py'`);
  if (port != null) {
    tryExec(`pkill -9 -f '[e]xodia_perception_stream.py.*--port ${port}'`);
  }
  killOrphanCapturePowerShell();
}

function tryExec(command: string): void {
  try {
    execSync(command, { stdio: 'ignore' });
  } catch {
    // expected when no process matched
  }
}
