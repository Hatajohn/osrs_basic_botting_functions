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
  showWorldTracks?: boolean;
  showTextHighlights?: boolean;
};

function worldMarkerTitle(m: PerceptionHudWorldMarker): string {
  const parts = [m.template, `score ${Number(m.score ?? 0).toFixed(2)}`];
  if (m.trackId != null) {
    parts.unshift(`#${m.trackId}`);
  }
  if (m.stable) {
    parts.push('stable');
  }
  if (m.velocityXY) {
    const [vx, vy] = m.velocityXY;
    if (Number.isFinite(vx) && Number.isFinite(vy) && (vx !== 0 || vy !== 0)) {
      parts.push(`v ${vx.toFixed(0)},${vy.toFixed(0)} px/s`);
    }
  }
  return parts.join(' · ');
}

/** Live HUD from /meta — percentage-anchored on image layer, survives zoom transform. */
export function PerceptionDebugOverlay({
  meta,
  imageRef,
  showInventoryDebug = true,
  showWorldTracks = true,
  showTextHighlights = false,
}: PerceptionDebugOverlayProps) {
  const computeLayout = useCallback(
    (img: HTMLImageElement) => computePerceptionHudLayout(img, meta),
    [meta],
  );

  const layout = useImageAnchoredLayout(imageRef, computeLayout, [meta]);

  const worldMarkers = useMemo(
    () => (showWorldTracks && layout ? layout.worldMarkers : []),
    [layout, showWorldTracks],
  );

  const invWatchMarkers = useMemo(
    () => (layout ? layout.invWatchMarkers : []),
    [layout],
  );

  const velocityArrows = useMemo(
    () => worldMarkers.filter((m) => m.velocityEnd != null),
    [worldMarkers],
  );

  const textMarkers = useMemo(
    () => (showTextHighlights && layout ? layout.textMarkers : []),
    [layout, showTextHighlights],
  );

  if (
    !layout &&
    worldMarkers.length === 0 &&
    invWatchMarkers.length === 0 &&
    textMarkers.length === 0
  ) {
    return null;
  }

  const { invBox, idEntries, slotMarkers, textStripBox } = layout ?? {
    invBox: null,
    idEntries: [],
    slotMarkers: [],
    textStripBox: null,
  };

  return (
    <div className="perception-debug-overlay" aria-hidden>
      {velocityArrows.length > 0 && (
        <svg className="perception-debug-overlay__velocity-svg" aria-hidden>
          {velocityArrows.map((m) => (
            <line
              key={`vel-${m.key}`}
              className={
                m.stable
                  ? 'perception-debug-overlay__velocity-line perception-debug-overlay__velocity-line--stable'
                  : 'perception-debug-overlay__velocity-line'
              }
              x1={m.left}
              y1={m.top}
              x2={m.velocityEnd!.left}
              y2={m.velocityEnd!.top}
            />
          ))}
        </svg>
      )}
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
      {worldMarkers.map((m) => (
        <span
          key={m.key}
          className={
            m.stable
              ? 'perception-debug-overlay__world-dot perception-debug-overlay__world-dot--stable'
              : m.trackId != null
                ? 'perception-debug-overlay__world-dot perception-debug-overlay__world-dot--tracked'
                : 'perception-debug-overlay__world-dot'
          }
          style={{ left: m.left, top: m.top, borderColor: m.color }}
          title={worldMarkerTitle(m)}
        >
          <span
            className="perception-debug-overlay__world-dot-core"
            style={{ backgroundColor: m.color }}
          />
          {m.trackId != null && (
            <span className="perception-debug-overlay__world-dot-id">{m.trackId}</span>
          )}
        </span>
      ))}
      {invWatchMarkers.map((m) => (
        <span
          key={m.key}
          className="perception-debug-overlay__track-dot"
          style={{ left: m.left, top: m.top, backgroundColor: m.color }}
          title={`${m.template}${m.score != null ? ` (${m.score.toFixed(2)})` : ''}`}
        />
      ))}
      {showTextHighlights && textStripBox && (
        <div
          className="perception-debug-overlay__text-strip"
          style={{
            left: textStripBox.left,
            top: textStripBox.top,
            width: textStripBox.width,
            height: textStripBox.height,
          }}
          title="Text scan ROI"
        />
      )}
      {showTextHighlights &&
        textMarkers.map((m) => (
          <div
            key={m.key}
            className="perception-debug-overlay__text-hl"
            style={{
              left: m.left,
              top: m.top,
              width: m.width,
              height: m.height,
              ['--text-hl-color' as string]: m.color,
            }}
            title={`${m.text}`}
          />
        ))}
    </div>
  );
}
