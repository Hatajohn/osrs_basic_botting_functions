import fs from 'node:fs';
import path from 'node:path';
import { resolveSettings, loadSettings } from './settings';

export type TemplateWatchRegion = 'world' | 'inventory';

export type TemplateWatchEntry = {
  id: string;
  template: string;
  region: TemplateWatchRegion;
  enabled: boolean;
};

export type TemplateWatchlist = {
  version: 1;
  entries: TemplateWatchEntry[];
};

const WATCHLIST_VERSION = 1 as const;

function normalizeStem(template: string): string {
  const trimmed = template.trim();
  return trimmed.toLowerCase().endsWith('.png') ? trimmed.slice(0, -4) : trimmed;
}

export function watchlistFilePath(exodiaRoot: string): string {
  return path.join(exodiaRoot, 'ExodiaBotUI', 'template_watchlist.json');
}

export function controlFilePath(exodiaRoot: string): string {
  return path.join(exodiaRoot, 'captures', 'perception_stream_control.json');
}

function defaultWatchlist(): TemplateWatchlist {
  return { version: WATCHLIST_VERSION, entries: [] };
}

export function loadTemplateWatchlist(): TemplateWatchlist {
  const { resolvedExodiaRoot } = resolveSettings(loadSettings());
  const filePath = watchlistFilePath(resolvedExodiaRoot);
  if (!fs.existsSync(filePath)) {
    return defaultWatchlist();
  }
  try {
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as Partial<TemplateWatchlist>;
    const entries = Array.isArray(raw.entries)
      ? raw.entries
          .filter((e): e is TemplateWatchEntry => Boolean(e && typeof e === 'object'))
          .map((e, i) => ({
            id: String(e.id ?? `e${i}`),
            template: normalizeStem(String(e.template ?? '')),
            region: e.region === 'inventory' ? 'inventory' : 'world',
            enabled: e.enabled !== false,
          }))
          .filter((e) => e.template.length > 0)
      : [];
    return { version: WATCHLIST_VERSION, entries };
  } catch {
    return defaultWatchlist();
  }
}

export function enabledWorldTemplates(watchlist: TemplateWatchlist): string[] {
  return watchlist.entries
    .filter((e) => e.enabled && e.region === 'world')
    .map((e) => normalizeStem(e.template));
}

export function enabledInventoryTemplates(watchlist: TemplateWatchlist): string[] {
  return watchlist.entries
    .filter((e) => e.enabled && e.region === 'inventory')
    .map((e) => normalizeStem(e.template));
}

function readControlFile(exodiaRoot: string): Record<string, unknown> {
  const filePath = controlFilePath(exodiaRoot);
  if (!fs.existsSync(filePath)) {
    return { invalidate: false, world_templates: [] };
  }
  try {
    const data = JSON.parse(fs.readFileSync(filePath, 'utf8')) as Record<string, unknown>;
    return typeof data === 'object' && data !== null ? data : { invalidate: false };
  } catch {
    return { invalidate: false, world_templates: [] };
  }
}

/** Write watchlist JSON and push enabled world templates to the stream control file. */
export function saveTemplateWatchlist(watchlist: TemplateWatchlist): TemplateWatchlist {
  const { resolvedExodiaRoot } = resolveSettings(loadSettings());
  const filePath = watchlistFilePath(resolvedExodiaRoot);
  const normalized: TemplateWatchlist = {
    version: WATCHLIST_VERSION,
    entries: watchlist.entries.map((e, i) => ({
      id: e.id || `e${i}`,
      template: normalizeStem(e.template),
      region: e.region === 'inventory' ? 'inventory' : 'world',
      enabled: e.enabled !== false,
    })),
  };
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(normalized, null, 2), 'utf8');
  syncWatchlistToControlFile(resolvedExodiaRoot, normalized);
  return normalized;
}

export function syncWatchlistToControlFile(
  exodiaRoot: string,
  watchlist: TemplateWatchlist = loadTemplateWatchlist(),
): void {
  const filePath = controlFilePath(exodiaRoot);
  const existing = readControlFile(exodiaRoot);
  const next = {
    ...existing,
    invalidate: Boolean(existing.invalidate),
    world_templates: enabledWorldTemplates(watchlist),
    inventory_templates: enabledInventoryTemplates(watchlist),
  };
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(next, null, 2), 'utf8');
}

export function newWatchEntry(
  template: string,
  region: TemplateWatchRegion = 'world',
): TemplateWatchEntry {
  const id = `w${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  return {
    id,
    template: normalizeStem(template),
    region,
    enabled: true,
  };
}
