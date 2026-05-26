import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export type PlatformProfile = 'linux' | 'wsl' | 'win32' | 'darwin';

export function detectPlatform(): PlatformProfile {
  if (process.platform === 'win32') return 'win32';
  if (process.platform === 'darwin') return 'darwin';
  if (process.platform === 'linux') {
    if (process.env.WSL_DISTRO_NAME || process.env.WSLENV) return 'wsl';
    return 'linux';
  }
  return 'linux';
}

/** Default Exodia repo root: parent of ExodiaBotUI/. */
export function defaultExodiaRoot(): string {
  return path.resolve(__dirname, '..', '..');
}

export function resolveExodiaRoot(override?: string): string {
  const root = override?.trim() || defaultExodiaRoot();
  return path.resolve(root);
}

export function defaultPythonPath(exodiaRoot: string): string {
  const venvPython =
    process.platform === 'win32'
      ? path.join(exodiaRoot, 'exodia', 'Scripts', 'python.exe')
      : path.join(exodiaRoot, 'exodia', 'bin', 'python');

  if (fs.existsSync(venvPython)) return venvPython;
  return process.platform === 'win32' ? 'python' : 'python3';
}

export function resolvePython(exodiaRoot: string, override?: string): string {
  const candidate = override?.trim();
  if (candidate) return candidate;
  return defaultPythonPath(exodiaRoot);
}

export function resolveLogsDir(exodiaRoot: string, override?: string): string {
  if (override?.trim()) return path.resolve(override.trim());
  return path.join(exodiaRoot, 'logs');
}

export function resolveChainsDir(exodiaRoot: string, override?: string): string {
  if (override?.trim()) return path.resolve(override.trim());
  return path.join(exodiaRoot, 'ExodiaBotUI', 'chains');
}

export function pythonExists(pythonPath: string): boolean {
  if (!pythonPath.includes('/') && !pythonPath.includes('\\')) {
    return true;
  }
  return fs.existsSync(pythonPath);
}
