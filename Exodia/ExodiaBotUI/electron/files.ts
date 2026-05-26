import fs from 'node:fs';
import path from 'node:path';
import type { FileEntry, ListDirectoryResult, SelectFolderResult } from '../shared/ipc';

function sortEntries(entries: FileEntry[]): FileEntry[] {
  return entries.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'directory' ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  });
}

export function listDirectory(dirPath: string): ListDirectoryResult {
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
      entries.push({ name, path: entryPath, kind });
    }

    return { path: resolved, parentPath: parentDirectory(resolved), entries: sortEntries(entries) };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { path: resolved, parentPath: parentDirectory(resolved), entries: [], error: message };
  }
}

export function parentDirectory(dirPath: string): string | null {
  const resolved = path.resolve(dirPath);
  const parent = path.dirname(resolved);
  if (parent === resolved) return null;
  return parent;
}
