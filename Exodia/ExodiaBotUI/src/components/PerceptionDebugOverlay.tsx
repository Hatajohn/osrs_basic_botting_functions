import { useCallback, useMemo, type RefObject } from 'react';
import type { StreamMeta } from '../../shared/ipc';
import { useImageAnchoredLayout } from '../hooks/useImageAnchoredLayout';
import {
  computePerceptionHudLayout,
  type PerceptionHudInvWatchMarker,
  type PerceptionHudWorldMarker,
} from './overlayCoords';
import './PerceptionDebugOverlay.css';

type PerceptionDebugOverlayProps = {
  meta: StreamMeta | null | undefined;
  imageRef: RefObject<HTMLImageElement | null>;
  showInventoryDebug?: boolean;
  showInventoryTracks?: boolean;
  showWorldTracks?: boolean;
};

type TrackDot = {
  key: string;
  left: number;
  top: number;
  color: string;
  title: string;
};

function toTrackDots(
  worldMarkers: PerceptionHudWorldMarker[],
  invWatchMarkers: PerceptionHudInvWatchMarker[],
): TrackDot[] {
  const dots: TrackDot[] = [];
  for (const m of worldMarkers) {
    dots.push({
      key: m.key,
      left: m.left,
      top: m.top,
      color: m.color,
      title: `${m.template} (${m.score.toFixed(2)})`,
    });
  }
  for (const m of invWatchMarkers) {
    dots.push({
      key: m.key,
      left: m.left,
      top: m.top,
      color: m.color,
      title: `${m.template}${m.score != null ? ` (${m.score.toFixed(2)})` : ''}`,
    });
  }
  return dots;
}

/** Live HUD from /meta — img-anchored, replaced each poll, no fade. */
export function PerceptionDebugOverlay({
  meta,
  imageRef,
  showInventoryDebug = true,
  showInventoryTracks = true,
  showWorldTracks = true,
}: PerceptionDebugOverlayProps) {
  const computeLayout = useCallback(
    (img: HTMLImageElement) => computePerceptionHudLayout(img, meta),
    [meta],
  );

  const layout = useImageAnchoredLayout(imageRef, computeLayout, [meta]);

  const trackDots = useMemo(() => {
    if (!layout) return [];
    const world = showWorldTracks ? layout.worldMarkers : [];
    const inv = showInventoryTracks ? layout.invWatchMarkers : [];
    return toTrackDots(world, inv);
  }, [layout, showInventoryTracks, showWorldTracks]);

  if (!layout) return null;

  const { invBox, idEntries, slotMarkers } = layout;

  return (
    <div className="perception-debug-overlay" aria-hidden>
      {showInventoryDebug && idEntries.length > 0 && (
        <div className="perception-debug-overlay__id-list">
          <div className="perception-debug-overlay__id-list-title">IDs</div>
          <ol className="perception-debug-overlay__id-list-items">
            {idEntries.map((entry) => (
              <li key={entry.id} title={entry.id}>
                <span
                  className="perception-debug-overlay__id-swatch"
                  style={{ backgroundColor: entry.color }}
                  aria-hidden
                />
                <span
                  className="perception-debug-overlay__id-list-num"
                  style={{ color: entry.color }}
                >
                  {entry.index}
                </span>
                <span className="perception-debug-overlay__id-list-text">{entry.id}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {showInventoryDebug && invBox && (
        <div
          className="perception-debug-overlay__inv-rect"
          style={{
            left: invBox.left,
            top: invBox.top,
            width: invBox.width,
            height: invBox.height,
          }}
        />
      )}
      {showInventoryDebug &&
        slotMarkers.map((m) => (
          <span
            key={m.key}
            className="perception-debug-overlay__slot-dot"
            style={{
              left: m.left,
              top: m.top,
              backgroundColor: m.color,
              borderColor: m.color,
            }}
            title={`ID ${m.index}`}
          >
            {m.index}
          </span>
        ))}
      {trackDots.map((dot) => (
        <span
          key={dot.key}
          className="perception-debug-overlay__track-dot"
          style={{ left: dot.left, top: dot.top, backgroundColor: dot.color }}
          title={dot.title}
        />
      ))}
    </div>
  );
}
