import type { ActionClickPreview, StreamMeta } from '../../shared/ipc';

export type PointLayout = {
  left: number;
  top: number;
  score?: number;
  searchMode?: 'inventory' | 'playspace';
};

export type DisplayPoint = {
  left: number;
  top: number;
};

export type DisplayRect = DisplayPoint & {
  width: number;
  height: number;
};

export type UseOnLayout = {
  from: PointLayout;
  to: PointLayout;
};

export type ClickLayout = {
  selected: PointLayout;
  alternates: PointLayout[];
};

export type FindLayout = {
  markers: PointLayout[];
};

export type OverlayLayout = ClickLayout | UseOnLayout | FindLayout;

export type PerceptionHudSlotMarker = {
  key: string;
  /** 1-based index into idEntries for this slot's item id. */
  index: number;
  color: string;
  left: number;
  top: number;
};

export type PerceptionHudIdEntry = {
  id: string;
  /** 1-based list index. */
  index: number;
  color: string;
};

export type PerceptionHudWorldMarker = {
  key: string;
  template: string;
  score: number;
  left: number;
  top: number;
  color: string;
};

export type PerceptionHudInvWatchMarker = {
  key: string;
  template: string;
  score?: number | null;
  left: number;
  top: number;
  color: string;
};

export type PerceptionHudLayout = {
  invBox: DisplayRect | null;
  /** Distinct item ids in first-seen slot order (1-based index matches slot markers). */
  idEntries: PerceptionHudIdEntry[];
  slotMarkers: PerceptionHudSlotMarker[];
  worldMarkers: PerceptionHudWorldMarker[];
  invWatchMarkers: PerceptionHudInvWatchMarker[];
};

/** Up to 28 visually distinct colors — one per inventory slot / distinct item id. */
export const ID_PALETTE: readonly string[] = [
  '#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16', '#22c55e', '#10b981', '#14b8a6',
  '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899',
  '#f43f5e', '#e879f9', '#c084fc', '#818cf8', '#38bdf8', '#2dd4bf', '#4ade80', '#a3e635',
  '#facc15', '#fb923c', '#fb7185', '#f472b6',
];

export function idColorForIndex(oneBasedIndex: number): string {
  const i = Math.max(1, oneBasedIndex) - 1;
  return ID_PALETTE[i % ID_PALETTE.length] ?? ID_PALETTE[0]!;
}

/** OSRS inventory: 7 rows × 4 columns (matches bot_eyes.INV_ROWS / INV_COLS). */
const INV_ROWS = 7;
const INV_COLS = 4;

/** Reference panel size from bot_eyes.inventory_grid_layout defaults. */
const GRID_REF_W = 283;
const GRID_REF_H = 382;
const GRID_OFFSET_X = 30;
const GRID_OFFSET_Y = 20;
const GRID_TILE_W = 50;
const GRID_TILE_H = 45;
const GRID_GAP_X = 7;
const GRID_GAP_Y = 5;

function templateTrackColor(stem: string): string {
  let hash = 0;
  for (let i = 0; i < stem.length; i += 1) {
    hash = stem.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 85%, 55%)`;
}

function shortTemplateLabel(stem: string): string {
  return stem.length > 10 ? `${stem.slice(0, 9)}…` : stem;
}

export { shortTemplateLabel };

function imageWrapOffset(img: HTMLImageElement): { scaleX: number; scaleY: number; offsetLeft: number; offsetTop: number } | null {
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (nw <= 0 || nh <= 0) return null;

  const rect = img.getBoundingClientRect();
  const wrap = img.parentElement;
  if (!wrap) return null;
  const wrapRect = wrap.getBoundingClientRect();

  return {
    scaleX: rect.width / nw,
    scaleY: rect.height / nh,
    offsetLeft: rect.left - wrapRect.left,
    offsetTop: rect.top - wrapRect.top,
  };
}

/** Map native client-frame coords to wrap-local display pixels (handles letterboxing). */
export function clientXYToDisplay(
  img: HTMLImageElement,
  frameWidth: number,
  frameHeight: number,
  clientXY: [number, number],
): DisplayPoint | null {
  if (frameWidth <= 0 || frameHeight <= 0) return null;

  const mapped = imageWrapOffset(img);
  if (!mapped) return null;

  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  const px = (clientXY[0] / frameWidth) * nw;
  const py = (clientXY[1] / frameHeight) * nh;

  return {
    left: mapped.offsetLeft + px * mapped.scaleX,
    top: mapped.offsetTop + py * mapped.scaleY,
  };
}

/** Map native client-frame rect to wrap-local display pixels. */
export function clientRectToDisplay(
  img: HTMLImageElement,
  frameWidth: number,
  frameHeight: number,
  rect: [number, number, number, number],
): DisplayRect | null {
  if (frameWidth <= 0 || frameHeight <= 0) return null;

  const mapped = imageWrapOffset(img);
  if (!mapped) return null;

  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  const [x, y, w, h] = rect;
  const px = (x / frameWidth) * nw;
  const py = (y / frameHeight) * nh;
  const pw = (w / frameWidth) * nw;
  const ph = (h / frameHeight) * nh;

  return {
    left: mapped.offsetLeft + px * mapped.scaleX,
    top: mapped.offsetTop + py * mapped.scaleY,
    width: pw * mapped.scaleX,
    height: ph * mapped.scaleY,
  };
}

/** Slot center in client coords — scaled grid layout aligned with bot_eyes. */
export function inventorySlotCenterClient(
  ix: number,
  iy: number,
  iw: number,
  ih: number,
  row: number,
  col: number,
): { cx: number; cy: number } {
  const sx = iw / GRID_REF_W;
  const sy = ih / GRID_REF_H;
  const dx = Math.round(GRID_OFFSET_X * sx);
  const dy = Math.round(GRID_OFFSET_Y * sy);
  const tileW = Math.max(1, Math.round(GRID_TILE_W * sx));
  const tileH = Math.max(1, Math.round(GRID_TILE_H * sy));
  const gapX = Math.max(0, Math.round(GRID_GAP_X * sx));
  const gapY = Math.max(0, Math.round(GRID_GAP_Y * sy));
  const cx = ix + dx + col * (tileW + gapX) + tileW / 2;
  const cy = iy + dy + row * (tileH + gapY) + tileH / 2;
  return { cx, cy };
}

export function clientXYToLayout(
  img: HTMLImageElement,
  preview: ActionClickPreview,
  clientXY: [number, number],
  extra?: Pick<PointLayout, 'score' | 'searchMode'>,
): PointLayout | null {
  const { frameWidth, frameHeight } = preview;
  const point = clientXYToDisplay(img, frameWidth, frameHeight, clientXY);
  if (!point) return null;

  return {
    left: point.left,
    top: point.top,
    score: extra?.score,
    searchMode: extra?.searchMode,
  };
}

/** Collect distinct item ids in row-major slot order; indices are 1-based. */
export function buildItemIdIndex(
  items: (string | null)[][],
  occ?: boolean[][],
): { idList: string[]; idToIndex: Map<string, number> } {
  const seen = new Set<string>();
  const idList: string[] = [];
  for (let row = 0; row < INV_ROWS; row += 1) {
    for (let col = 0; col < INV_COLS; col += 1) {
      if (occ && !occ[row]?.[col]) continue;
      const raw = items[row]?.[col];
      if (raw == null || raw === '') continue;
      const id = String(raw);
      if (seen.has(id)) continue;
      seen.add(id);
      idList.push(id);
    }
  }
  const idToIndex = new Map(idList.map((id, i) => [id, i + 1]));
  return { idList, idToIndex };
}

export function computePerceptionHudLayout(
  img: HTMLImageElement,
  meta: StreamMeta | null | undefined,
): PerceptionHudLayout | null {
  const frameWidth = meta?.frame_width ?? 0;
  const frameHeight = meta?.frame_height ?? 0;
  if (frameWidth <= 0 || frameHeight <= 0) return null;

  const inventory = meta?.perception?.inventory;
  const world = meta?.perception?.world;

  let invBox: DisplayRect | null = null;
  const rect = inventory?.inventory_rect;
  if (rect && rect.length === 4) {
    invBox = clientRectToDisplay(img, frameWidth, frameHeight, rect as [number, number, number, number]);
  }

  const items = inventory?.slot_items;
  const occ = inventory?.occupancy;
  const { idList, idToIndex } =
    items?.length ? buildItemIdIndex(items, occ) : { idList: [], idToIndex: new Map<string, number>() };

  const idEntries: PerceptionHudIdEntry[] = idList.map((id, i) => {
    const index = i + 1;
    return { id, index, color: idColorForIndex(index) };
  });

  const slotMarkers: PerceptionHudSlotMarker[] = [];
  if (rect && rect.length === 4 && items?.length) {
    const [ix, iy, iw, ih] = rect;
    for (let row = 0; row < INV_ROWS; row += 1) {
      for (let col = 0; col < INV_COLS; col += 1) {
        if (occ && !occ[row]?.[col]) continue;
        const raw = items[row]?.[col];
        if (raw == null || raw === '') continue;
        const index = idToIndex.get(String(raw));
        if (index == null) continue;
        const { cx, cy } = inventorySlotCenterClient(ix, iy, iw, ih, row, col);
        const pos = clientXYToDisplay(img, frameWidth, frameHeight, [cx, cy]);
        if (!pos) continue;
        slotMarkers.push({
          key: `${row}-${col}`,
          index,
          color: idColorForIndex(index),
          left: pos.left,
          top: pos.top,
        });
      }
    }
  }

  const worldMarkers: PerceptionHudWorldMarker[] = [];
  for (const [i, hit] of (world?.hits ?? []).entries()) {
    const xy = hit.client_xy ?? [0, 0];
    const pos = clientXYToDisplay(img, frameWidth, frameHeight, [xy[0], xy[1]]);
    if (!pos) continue;
    worldMarkers.push({
      key: `world-${i}-${hit.template}`,
      template: hit.template,
      score: hit.score,
      left: pos.left,
      top: pos.top,
      color: templateTrackColor(hit.template),
    });
  }

  const invWatchMarkers: PerceptionHudInvWatchMarker[] = [];
  const invWatch = inventory?.inventory_watch ?? [];
  if (rect && rect.length === 4 && invWatch.length) {
    const [ix, iy, iw, ih] = rect;
    for (const entry of invWatch) {
      const points = entry.points ?? [];
      if (points.length > 0) {
        for (const pt of points) {
          const xy = pt.client_xy ?? [];
          if (xy.length < 2) continue;
          const pos = clientXYToDisplay(img, frameWidth, frameHeight, [xy[0], xy[1]]);
          if (!pos) continue;
          const slot = pt.slot ?? [];
          invWatchMarkers.push({
            key: `inv-watch-${entry.template}-${slot[0]}-${slot[1]}-${xy[0]}-${xy[1]}`,
            template: entry.template,
            score: typeof pt.score === 'number' ? pt.score : entry.best_score ?? null,
            left: pos.left,
            top: pos.top,
            color: templateTrackColor(entry.template),
          });
        }
        continue;
      }
      for (const [row, col] of entry.slots ?? []) {
        const { cx, cy } = inventorySlotCenterClient(ix, iy, iw, ih, row, col);
        const pos = clientXYToDisplay(img, frameWidth, frameHeight, [cx, cy]);
        if (!pos) continue;
        invWatchMarkers.push({
          key: `inv-watch-${entry.template}-${row}-${col}`,
          template: entry.template,
          score: entry.best_score ?? null,
          left: pos.left,
          top: pos.top,
          color: templateTrackColor(entry.template),
        });
      }
    }
  }

  if (!invBox && idEntries.length === 0 && slotMarkers.length === 0 && worldMarkers.length === 0 && invWatchMarkers.length === 0) {
    return null;
  }

  return { invBox, idEntries, slotMarkers, worldMarkers, invWatchMarkers };
}

export function computeClickLayout(img: HTMLImageElement, preview: ActionClickPreview): ClickLayout | null {
  if (!preview.clickClientXY) return null;
  const selected = clientXYToLayout(img, preview, preview.clickClientXY, { score: preview.score });
  if (!selected) return null;

  const alternates: PointLayout[] = [];
  for (const cand of preview.matchCandidates ?? []) {
    if (cand.selected) continue;
    const layout = clientXYToLayout(img, preview, cand.clickClientXY, {
      score: cand.score,
      searchMode: cand.searchMode,
    });
    if (layout) alternates.push(layout);
  }

  return { selected, alternates };
}

export function computeFindLayout(img: HTMLImageElement, preview: ActionClickPreview): FindLayout | null {
  const markers: PointLayout[] = [];
  for (const cand of preview.matchCandidates ?? []) {
    const layout = clientXYToLayout(img, preview, cand.clickClientXY, {
      score: cand.score,
      searchMode: cand.searchMode,
    });
    if (layout) markers.push(layout);
  }
  return markers.length > 0 ? { markers } : null;
}

export function computeUseOnLayout(
  img: HTMLImageElement,
  preview: ActionClickPreview,
): UseOnLayout | null {
  if (!preview.fromClientXY || !preview.toClientXY) return null;
  const from = clientXYToLayout(img, preview, preview.fromClientXY);
  const to = clientXYToLayout(img, preview, preview.toClientXY);
  if (!from || !to) return null;
  return { from, to };
}

export function computeOverlayLayout(
  img: HTMLImageElement,
  preview: ActionClickPreview,
): OverlayLayout | null {
  if (preview.previewMode === 'find') {
    return computeFindLayout(img, preview);
  }
  if (preview.previewMode === 'use_on' || (preview.fromClientXY && preview.toClientXY)) {
    return computeUseOnLayout(img, preview);
  }
  return computeClickLayout(img, preview);
}

export function isUseOnLayout(layout: OverlayLayout | null): layout is UseOnLayout {
  return layout != null && 'from' in layout && 'to' in layout;
}

export function isClickLayout(layout: OverlayLayout | null): layout is ClickLayout {
  return layout != null && 'selected' in layout;
}

export function isFindLayout(layout: OverlayLayout | null): layout is FindLayout {
  return layout != null && 'markers' in layout;
}
