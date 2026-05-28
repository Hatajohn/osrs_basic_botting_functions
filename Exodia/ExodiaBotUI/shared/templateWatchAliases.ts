/** Map watchlist row stems to playspace scan stems (inventory icon → world spot PNG). */
const WORLD_SCAN_ALIASES: Record<string, string> = {
  infernal_eel: 'osrs_infernalEel',
  infernal_eel_spot: 'osrs_infernalEel',
};

export function normalizeWatchStem(template: string): string {
  const trimmed = template.trim();
  return trimmed.toLowerCase().endsWith('.png') ? trimmed.slice(0, -4) : trimmed;
}

export function worldScanStem(watchStem: string): string {
  const normalized = normalizeWatchStem(watchStem);
  return WORLD_SCAN_ALIASES[normalized.toLowerCase()] ?? normalized;
}

export function worldScanStemsForWatchlist(
  entries: Array<{ template: string; world: boolean }>,
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of entries) {
    if (!entry.world) continue;
    const stem = worldScanStem(entry.template);
    const key = stem.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(stem);
  }
  return out;
}
