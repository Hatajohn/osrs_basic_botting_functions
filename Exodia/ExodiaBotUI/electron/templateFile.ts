import fs from 'node:fs';
import path from 'node:path';
import { type BrowserWindow, dialog } from 'electron';
import type { SelectTemplateFileResult } from '../shared/ipc';
import { loadSettings, resolveSettings } from './settings';

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp']);

function defaultBrowseDir(exodiaRoot: string): string {
  const imagesDir = path.join(exodiaRoot, 'images');
  if (fs.existsSync(imagesDir)) return imagesDir;
  const capturesDir = path.join(exodiaRoot, 'captures');
  if (fs.existsSync(capturesDir)) return capturesDir;
  return exodiaRoot;
}

function isUnderDir(filePath: string, dirPath: string): boolean {
  const rel = path.relative(dirPath, filePath);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

export async function selectTemplateFile(
  parentWindow: BrowserWindow | null,
): Promise<SelectTemplateFileResult> {
  const { resolvedExodiaRoot } = resolveSettings(loadSettings());
  const imagesDir = path.join(resolvedExodiaRoot, 'images');
  const defaultPath = defaultBrowseDir(resolvedExodiaRoot);

  const result = await dialog.showOpenDialog(parentWindow ?? undefined, {
    title: 'Select template image',
    defaultPath,
    filters: [
      { name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'] },
      { name: 'All files', extensions: ['*'] },
    ],
    properties: ['openFile'],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }

  const filePath = path.resolve(result.filePaths[0]);
  const ext = path.extname(filePath).toLowerCase();
  if (!IMAGE_EXTENSIONS.has(ext)) {
    return { canceled: false, ok: false, error: `Not an image file: ${path.basename(filePath)}` };
  }

  const name = path.basename(filePath);
  const inImages = fs.existsSync(imagesDir) && isUnderDir(filePath, imagesDir);
  const capturesDir = path.join(resolvedExodiaRoot, 'captures');
  const inCaptures = fs.existsSync(capturesDir) && isUnderDir(filePath, capturesDir);
  const imagesCopy = path.join(imagesDir, name);
  const useImagesCopy =
    inCaptures && fs.existsSync(imagesCopy) && name === 'osrs_infernalEel.png';

  return {
    canceled: false,
    ok: true,
    path: filePath,
    name,
    template: name,
    templatePath: inImages || useImagesCopy ? undefined : filePath,
    role: name === 'osrs_infernalEel.png' ? 'fishing_spot' : name === 'infernal_eel.png' ? 'inventory_item' : undefined,
  };
}
