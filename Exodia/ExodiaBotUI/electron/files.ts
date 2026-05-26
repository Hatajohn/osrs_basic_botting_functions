import fs from 'node:fs';
import path from 'node:path';
import type { FileEntry, ListDirectoryOptions, ListDirectoryResult, ReadTextFileResult } from '../shared/ipc';

const MAX_TEXT_BYTES = 512 * 1024;

function isMarkdownFile(name: string): boolean {
  return name.toLowerCase().endsWith('.md');
}

function sortEntries(entries: FileEntry[]): FileEntry[] {
  return entries.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'directory' ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  });
}

export function listDirectory(dirPath: string, options?: ListDirectoryOptions): ListDirectoryResult {
  const markdownOnly = options?.markdownOnly ?? false;
  const resolved = path.resolve(dirPath);
  if (!fs.existsSync(resolved)) {
    return { path: resolved, parentPath: parentDirectory(resolved), entries: [], error: `Folder not found: ${resolved}` };
  }
  if (!fs.statSync(resolved).isDirectory()) {
    return { path: resolved, parentPath: parentDirectory(resolved), entries: [], error: `Not a directory: ${resolved}` };
  }

  try {
    const names = fs.readdirSync(resolved);
    const entries: FileEntry[] = [];

    for (const name of names) {
      if (name.startsWith('.')) continue;
      const entryPath = path.join(resolved, name);
      let kind: FileEntry['kind'] = 'file';
      try {
        kind = fs.statSync(entryPath).isDirectory() ? 'directory' : 'file';
      } catch {
        continue;
      }
      if (markdownOnly && kind === 'file' && !isMarkdownFile(name)) {
        continue;
      }
      entries.push({ name, path: entryPath, kind });
    }

    return { path: resolved, parentPath: parentDirectory(resolved), entries: sortEntries(entries) };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { path: resolved, parentPath: parentDirectory(resolved), entries: [], error: message };
  }
}

export function readTextFile(filePath: string): ReadTextFileResult {
  const resolved = path.resolve(filePath);
  try {
    if (!fs.existsSync(resolved)) {
      return { ok: false, path: resolved, error: `File not found: ${resolved}` };
    }
    const stat = fs.statSync(resolved);
    if (!stat.isFile()) {
      return { ok: false, path: resolved, error: `Not a file: ${resolved}` };
    }
    if (!isMarkdownFile(resolved)) {
      return { ok: false, path: resolved, error: 'Only markdown (.md) files can be loaded as specs' };
    }
    if (stat.size > MAX_TEXT_BYTES) {
      return { ok: false, path: resolved, error: `File too large (${stat.size} bytes, max ${MAX_TEXT_BYTES})` };
    }
    const content = fs.readFileSync(resolved, 'utf8');
    return { ok: true, path: resolved, content, name: path.basename(resolved) };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, path: resolved, error: message };
  }
}

export function parentDirectory(dirPath: string): string | null {
  const resolved = path.resolve(dirPath);
  const parent = path.dirname(resolved);
  if (parent === resolved) return null;
  return parent;
}
