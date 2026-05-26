import type { ActionClickPreview, MatchCandidatePreview, RunSingleActionResult } from '../shared/ipc';

function numPair(value: unknown): [number, number] | undefined {
  if (!Array.isArray(value) || value.length < 2) return undefined;
  const a = Number(value[0]);
  const b = Number(value[1]);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return undefined;
  return [Math.round(a), Math.round(b)];
}

function frameSize(inner: Record<string, unknown>): { w: number; h: number } | undefined {
  const frameWidth =
    typeof inner.frame_width === 'number' ? inner.frame_width : Number(inner.frame_width);
  const frameHeight =
    typeof inner.frame_height === 'number' ? inner.frame_height : Number(inner.frame_height);
  if (!Number.isFinite(frameWidth) || !Number.isFinite(frameHeight)) return undefined;
  if (frameWidth <= 0 || frameHeight <= 0) return undefined;
  return { w: Math.round(frameWidth), h: Math.round(frameHeight) };
}

function parseMatchCandidates(inner: Record<string, unknown>): MatchCandidatePreview[] | undefined {
  const raw = inner.match_candidates;
  if (!Array.isArray(raw) || raw.length < 2) return undefined;
  const out: MatchCandidatePreview[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const rec = entry as Record<string, unknown>;
    const clickClientXY = numPair(rec.click_client_xy);
    if (!clickClientXY) continue;
    out.push({
      clickClientXY,
      score: typeof rec.score === 'number' ? rec.score : undefined,
      selected: rec.selected === true,
    });
  }
  return out.length >= 2 ? out : undefined;
}

function slotLabel(inner: Record<string, unknown>): string | undefined {
  const src = inner.source_slot;
  const dst = inner.dest_slot;
  if (Array.isArray(src) && Array.isArray(dst) && src.length >= 2 && dst.length >= 2) {
    return `(${src[0]},${src[1]}) → (${dst[0]},${dst[1]})`;
  }
  if (typeof inner.slot === 'string') return inner.slot;
  return undefined;
}

export function clickPreviewFromActionResult(
  blockId: string,
  inner?: Record<string, unknown>,
): ActionClickPreview | undefined {
  if (!inner) return undefined;
  const dims = frameSize(inner);
  if (!dims) return undefined;

  const fromClientXY = numPair(inner.from_click_client_xy);
  const toClientXY = numPair(inner.to_click_client_xy);
  if (
    inner.previewMode === 'use_on' ||
    (fromClientXY && toClientXY)
  ) {
    if (!fromClientXY || !toClientXY) return undefined;
    return {
      blockId,
      previewMode: 'use_on',
      label: typeof inner.label === 'string' ? inner.label : undefined,
      searchMode: 'inventory',
      fromClientXY,
      toClientXY,
      fromScreenXY: numPair(inner.from_screen_xy),
      toScreenXY: numPair(inner.to_screen_xy),
      sourceId: typeof inner.sourceId === 'string' ? inner.sourceId : undefined,
      destId: typeof inner.destId === 'string' ? inner.destId : undefined,
      frameWidth: dims.w,
      frameHeight: dims.h,
      slot: slotLabel(inner),
    };
  }

  const clickClientXY = numPair(inner.click_client_xy);
  const screenXY = numPair(inner.screen_xy);
  if (!clickClientXY || !screenXY) return undefined;

  return {
    blockId,
    previewMode: 'click',
    label: typeof inner.label === 'string' ? inner.label : undefined,
    searchMode:
      inner.searchMode === 'playspace' || inner.searchMode === 'inventory'
        ? inner.searchMode
        : undefined,
    screenXY,
    clickClientXY,
    frameWidth: dims.w,
    frameHeight: dims.h,
    score: typeof inner.score === 'number' ? inner.score : undefined,
    slot: typeof inner.slot === 'string' ? inner.slot : undefined,
    matchCandidates: parseMatchCandidates(inner),
    matchCount:
      typeof inner.match_count === 'number'
        ? inner.match_count
        : typeof inner.matches === 'number'
          ? inner.matches
          : undefined,
  };
}

export function attachClickPreview(
  blockId: string,
  response: RunSingleActionResult,
): RunSingleActionResult {
  const preview = clickPreviewFromActionResult(blockId, response.result);
  if (!preview) return response;
  return { ...response, clickPreview: preview };
}
