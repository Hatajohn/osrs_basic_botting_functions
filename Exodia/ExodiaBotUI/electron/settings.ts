import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';
import {
  defaultExodiaRoot,
  resolveChainsDir,
  resolveExodiaRoot,
  resolveLogsDir,
  resolvePython,
} from './paths';

import type { ExodiaSettings } from '../shared/settings';

export type { ExodiaSettings };

export type ResolvedSettings = ExodiaSettings & {
  resolvedExodiaRoot: string;
  resolvedPythonPath: string;
  resolvedLogsDir: string;
  resolvedChainsDir: string;
  resolvedScriptsFolder: string;
};

function configPath(): string {
  return path.join(app.getPath('userData'), 'config.json');
}

function defaultSettings(): ExodiaSettings {
  const exodiaRoot = defaultExodiaRoot();
  return {
    exodiaRoot,
    pythonPath: '',
    logsDir: '',
    chainsDir: '',
    scriptsFolder: '',
    streamPort: 8765,
  };
}

export function loadSettings(): ExodiaSettings {
  const defaults = defaultSettings();
  try {
    const raw = fs.readFileSync(configPath(), 'utf8');
    const parsed = JSON.parse(raw) as Partial<ExodiaSettings>;
    return {
      ...defaults,
      ...parsed,
      streamPort: parsed.streamPort ?? defaults.streamPort,
    };
  } catch {
    return defaults;
  }
}

export function saveSettings(partial: Partial<ExodiaSettings>): ExodiaSettings {
  const current = loadSettings();
  const next: ExodiaSettings = {
    ...current,
    ...partial,
    streamPort: partial.streamPort ?? current.streamPort,
  };
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(next, null, 2), 'utf8');
  return next;
}

export function resolveScriptsFolder(exodiaRoot: string, override?: string): string {
  if (override?.trim()) return path.resolve(override.trim());
  return exodiaRoot;
}

export function resolveSettings(settings: ExodiaSettings): ResolvedSettings {
  const resolvedExodiaRoot = resolveExodiaRoot(settings.exodiaRoot);
  const resolvedPythonPath = resolvePython(resolvedExodiaRoot, settings.pythonPath);
  const resolvedLogsDir = resolveLogsDir(resolvedExodiaRoot, settings.logsDir);
  const resolvedChainsDir = resolveChainsDir(resolvedExodiaRoot, settings.chainsDir);
  const resolvedScriptsFolder = resolveScriptsFolder(resolvedExodiaRoot, settings.scriptsFolder);
  return {
    ...settings,
    resolvedExodiaRoot,
    resolvedPythonPath,
    resolvedLogsDir,
    resolvedChainsDir,
    resolvedScriptsFolder,
  };
}

export function getConfigFilePath(): string {
  return configPath();
}
