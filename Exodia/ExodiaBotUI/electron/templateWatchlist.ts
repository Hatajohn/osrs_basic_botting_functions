import fs from 'node:fs';
import path from 'node:path';
import { worldScanStemsForWatchlist } from '../shared/templateWatchAliases';
import { resolveSettings, loadSettings } from './settings';

export type TemplateWatchRegion = 'world' | 'inventory';

export type TemplateWatchEntry = {
  id: string;
  template: string;
  world: boolean;
  inventory: boolean;
};

export type TemplateWatchlist = {
  version: 1;
  entries: TemplateWatchEntry[];
};

const WATCHLIST_VERSION = 1 as const;

type LegacyTemplateWatchEntry = {
  id?: string;
  template?: string;
  region?: string;
  enabled?: boolean;
  world?: boolean;
  inventory?: boolean;
};

function normalizeStem(template: string): string {
  const trimmed = template.trim();
  return trimmed.toLowerCase().endsWith('.png') ? trimmed.slice(0, -4) : trimmed;
}

function parseLegacyEntry(raw: LegacyTemplateWatchEntry, index: number): TemplateWatchEntry | null {
  const template = normalizeStem(String(raw.template ?? ''));
  if (!template) return null;

  if ('world' in raw || 'inventory' in raw) {
    return {
      id: String(raw.id ?? `e${index}`),
      template,
      world: raw.world === true,
      inventory: raw.inventory === true,
    };
  }

  const region = raw.region === 'inventory' ? 'inventory' : 'world';
  const enabled = raw.enabled !== false;
  return {
    id: String(raw.id ?? `e${index}`),
    template,
    world: region === 'world' && enabled,
    inventory: region === 'inventory' && enabled,
  };
}

function mergeEntries(entries: TemplateWatchEntry[]): TemplateWatchEntry[] {
  const byTemplate = new Map<string, TemplateWatchEntry>();
  for (const entry of entries) {
    const existing = byTemplate.get(entry.template);
    if (!existing) {
      byTemplate.set(entry.template, entry);
      continue;
    }
    byTemplate.set(entry.template, {
      ...existing,
      world: existing.world || entry.world,
      inventory: existing.inventory || entry.inventory,
    });
  }
  return [...byTemplate.values()];
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
    const parsed = Array.isArray(raw.entries)
      ? raw.entries
          .map((e, i) => parseLegacyEntry((e ?? {}) as LegacyTemplateWatchEntry, i))
          .filter((e): e is TemplateWatchEntry => e != null)
      : [];
    return { version: WATCHLIST_VERSION, entries: mergeEntries(parsed) };
  } catch {
    return defaultWatchlist();
  }
}

export function enabledWorldTemplates(watchlist: TemplateWatchlist): string[] {
  return worldScanStemsForWatchlist(watchlist.entries);
}

export function enabledInventoryTemplates(watchlist: TemplateWatchlist): string[] {
  return watchlist.entries.filter((e) => e.inventory).map((e) => normalizeStem(e.template));
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

/** Write watchlist JSON and push enabled templates to the stream control file. */
export function saveTemplateWatchlist(watchlist: TemplateWatchlist): TemplateWatchlist {
  const { resolvedExodiaRoot } = resolveSettings(loadSettings());
  const filePath = watchlistFilePath(resolvedExodiaRoot);
  const normalized: TemplateWatchlist = {
    version: WATCHLIST_VERSION,
    entries: mergeEntries(
      watchlist.entries.map((e, i) => ({
        id: e.id || `e${i}`,
        template: normalizeStem(e.template),
        world: e.world === true,
        inventory: e.inventory === true,
      })),
    ).filter((e) => e.template.length > 0),
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
    world: region === 'world',
    inventory: region === 'inventory',
  };
}
