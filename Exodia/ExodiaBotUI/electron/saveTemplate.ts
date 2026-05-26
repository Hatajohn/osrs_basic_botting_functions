import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import type { SaveTemplateRequest, SaveTemplateResult } from '../shared/ipc';
import { pythonExists } from './paths';
import { loadSettings, resolveSettings } from './settings';

const SCRIPT_NAME = 'exodia_save_template.py';

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

function spawnSaveCommand(
  argv: string[],
): Promise<{ parsed: Record<string, unknown> | null; stderr: string; code: number | null }> {
  const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
  const scriptPath = path.join(resolvedExodiaRoot, SCRIPT_NAME);

  if (!pythonExists(resolvedPythonPath)) {
    return Promise.resolve({
      parsed: null,
      stderr: `Python not found at: ${resolvedPythonPath}`,
      code: null,
    });
  }
  if (!fs.existsSync(scriptPath)) {
    return Promise.resolve({
      parsed: null,
      stderr: `Save template script not found: ${scriptPath}`,
      code: null,
    });
  }

  return new Promise((resolve) => {
    const child = spawn(resolvedPythonPath, [scriptPath, ...argv], {
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
      resolve({ parsed: null, stderr: err.message, code: null });
    });

    child.on('close', (code) => {
      resolve({ parsed: parseJsonLine(stdout), stderr: stderr.trim(), code });
    });
  });
}

function mapResult(parsed: Record<string, unknown> | null, stderr: string, code: number | null): SaveTemplateResult {
  if (!parsed) {
    return { ok: false, error: stderr || `Save failed (exit ${code ?? 'unknown'})` };
  }
  if (!parsed.ok) {
    return {
      ok: false,
      error: typeof parsed.error === 'string' ? parsed.error : 'save_failed',
      hint: typeof parsed.hint === 'string' ? parsed.hint : undefined,
      templatePath: typeof parsed.templatePath === 'string' ? parsed.templatePath : undefined,
    };
  }
  return {
    ok: true,
    kind: parsed.kind === 'world' ? 'world' : 'inventory',
    dest: parsed.dest === 'images' ? 'images' : 'items',
    itemId: typeof parsed.itemId === 'string' ? parsed.itemId : undefined,
    displayName: typeof parsed.displayName === 'string' ? parsed.displayName : undefined,
    templateFile: typeof parsed.templateFile === 'string' ? parsed.templateFile : undefined,
    templatePath: typeof parsed.templatePath === 'string' ? parsed.templatePath : undefined,
    slot: Array.isArray(parsed.slot) ? (parsed.slot as [number, number]) : undefined,
    rect: Array.isArray(parsed.rect) ? (parsed.rect as [number, number, number, number]) : undefined,
  };
}

export async function saveTemplate(request: SaveTemplateRequest): Promise<SaveTemplateResult> {
  const name = (request.name ?? '').trim();
  if (!name) {
    return { ok: false, error: 'missing_name' };
  }

  if (request.mode === 'import') {
    const filePath = (request.sourcePath ?? '').trim();
    if (!filePath) {
      return { ok: false, error: 'missing_source_path' };
    }
    const kind = request.dest === 'images' ? 'images' : 'items';
    const argv = ['import', '--kind', kind, '--name', name, '--path', filePath];
    if (request.overwrite) argv.push('--overwrite');
    const { parsed, stderr, code } = await spawnSaveCommand(argv);
    return mapResult(parsed, stderr, code);
  }

  if (request.mode === 'world') {
    const rect = request.rect;
    if (!rect || rect.length < 4) {
      return { ok: false, error: 'missing_rect', hint: 'Set crop x,y,w,h or use Fill from preview' };
    }
    const argv = [
      'world',
      '--name',
      name,
      '--rect',
      rect.map((n) => Math.round(n)).join(','),
    ];
    if (request.overwrite) argv.push('--overwrite');
    const { parsed, stderr, code } = await spawnSaveCommand(argv);
    return mapResult(parsed, stderr, code);
  }

  const slot = request.slot;
  if (!slot || slot.length < 2) {
    return { ok: false, error: 'missing_slot', hint: 'Set inventory slot row,col' };
  }
  const argv = [
    'inventory',
    '--name',
    name,
    '--slot',
    `${Math.round(slot[0])},${Math.round(slot[1])}`,
  ];
  if (request.overwrite) argv.push('--overwrite');
  const { parsed, stderr, code } = await spawnSaveCommand(argv);
  return mapResult(parsed, stderr, code);
}
