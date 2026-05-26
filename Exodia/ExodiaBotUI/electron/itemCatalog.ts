import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import type {
  ItemCatalogListResult,
  ResolveTemplateItemResult,
} from '../shared/ipc';
import { pythonExists } from './paths';
import { loadSettings, resolveSettings } from './settings';

const SCRIPT_NAME = 'exodia_item_catalog.py';

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

function spawnCatalogCommand(
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
      stderr: `Catalog script not found: ${scriptPath}`,
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

export async function listItemCatalog(): Promise<ItemCatalogListResult> {
  const { parsed, stderr, code } = await spawnCatalogCommand(['list']);
  if (!parsed || !parsed.ok) {
    return {
      ok: false,
      error: stderr || `Catalog list failed (exit ${code ?? 'unknown'})`,
      named: [],
      fingerprints: [],
    };
  }

  return {
    ok: true,
    itemsDir: typeof parsed.itemsDir === 'string' ? parsed.itemsDir : undefined,
    named: Array.isArray(parsed.named) ? (parsed.named as ItemCatalogListResult['named']) : [],
    fingerprints: Array.isArray(parsed.fingerprints)
      ? (parsed.fingerprints as ItemCatalogListResult['fingerprints'])
      : [],
  };
}

export async function resolveTemplateItem(
  imagePath: string,
): Promise<ResolveTemplateItemResult> {
  const { parsed, stderr, code } = await spawnCatalogCommand([
    'resolve',
    '--path',
    imagePath,
  ]);
  if (!parsed) {
    return {
      ok: false,
      error: stderr || `Catalog resolve failed (exit ${code ?? 'unknown'})`,
    };
  }

  if (!parsed.ok) {
    return {
      ok: false,
      error: typeof parsed.error === 'string' ? parsed.error : 'resolve_failed',
    };
  }

  if (!parsed.matched) {
    return {
      ok: true,
      matched: false,
      bestNamed:
        typeof parsed.bestNamed === 'string' ? parsed.bestNamed : undefined,
      bestNamedScore:
        typeof parsed.bestNamedScore === 'number' ? parsed.bestNamedScore : undefined,
      bestFingerprintScore:
        typeof parsed.bestFingerprintScore === 'number'
          ? parsed.bestFingerprintScore
          : undefined,
    };
  }

  return {
    ok: true,
    matched: true,
    kind: parsed.kind === 'fingerprint' ? 'fingerprint' : 'named',
    itemId: typeof parsed.itemId === 'string' ? parsed.itemId : undefined,
    displayName:
      typeof parsed.displayName === 'string' ? parsed.displayName : undefined,
    score: typeof parsed.score === 'number' ? parsed.score : undefined,
    templateFile:
      typeof parsed.templateFile === 'string' ? parsed.templateFile : undefined,
    templatePath:
      typeof parsed.templatePath === 'string' ? parsed.templatePath : undefined,
  };
}
