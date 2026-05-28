import { useCallback } from 'react';
import type { ActionClickPreview } from '../../shared/ipc';
import { useImageAnchoredLayout } from '../hooks/useImageAnchoredLayout';
import {
  computeOverlayLayout,
  isClickLayout,
  isFindLayout,
  isUseOnLayout,
  type ClickLayout,
  type FindLayout,
  type OverlayLayout,
  type UseOnLayout,
} from './overlayCoords';
import './ActionClickOverlay.css';

type ActionClickOverlayProps = {
  preview: ActionClickPreview | null;
  imageRef: React.RefObject<HTMLImageElement | null>;
};

function UseOnOverlay({
  layout,
  preview,
}: {
  layout: UseOnLayout;
  preview: ActionClickPreview;
}) {
  const { from, to } = layout;
  const title = [
    preview.label ?? preview.blockId,
    preview.sourceId && preview.destId
      ? `${preview.sourceId} → ${preview.destId}`
      : null,
    preview.slot ?? null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="action-click-overlay" aria-hidden title={title}>
      <div
        className="action-click-overlay__marker action-click-overlay__marker--from"
        style={{ left: from.left, top: from.top }}
        title={`Use: ${preview.sourceId ?? 'source'}`}
      >
        <span className="action-click-overlay__dot action-click-overlay__dot--from" />
        <span className="action-click-overlay__label">Use</span>
      </div>
      <div
        className="action-click-overlay__marker action-click-overlay__marker--to"
        style={{ left: to.left, top: to.top }}
        title={`On: ${preview.destId ?? 'dest'}`}
      >
        <span className="action-click-overlay__dot action-click-overlay__dot--to" />
        <span className="action-click-overlay__label">On</span>
      </div>
    </div>
  );
}

function FindOverlay({
  layout,
  preview,
}: {
  layout: FindLayout;
  preview: ActionClickPreview;
}) {
  const worldCount = layout.markers.filter((m) => m.searchMode === 'playspace').length;
  const invCount = layout.markers.filter((m) => m.searchMode === 'inventory').length;

  return (
    <div
      className="action-click-overlay"
      aria-hidden
      title={`Find · ${worldCount} world · ${invCount} inventory`}
    >
      {layout.markers.map((marker, index) => {
        const isWorld = marker.searchMode === 'playspace';
        const region = isWorld ? 'World' : 'Inventory';
        const scoreNote =
          marker.score != null ? ` · score ${marker.score.toFixed(2)}` : '';
        return (
          <div
            key={`find-${index}-${marker.left}-${marker.top}-${marker.searchMode}`}
            className={`action-click-overlay__marker action-click-overlay__marker--find ${
              isWorld
                ? 'action-click-overlay__marker--find-world'
                : 'action-click-overlay__marker--find-inv'
            }`}
            style={{ left: marker.left, top: marker.top }}
            title={`${region}${scoreNote}`}
          >
            <span
              className={
                isWorld
                  ? 'action-click-overlay__find-ring action-click-overlay__find-ring--world'
                  : 'action-click-overlay__find-ring action-click-overlay__find-ring--inv'
              }
            />
          </div>
        );
      })}
      <div className="action-click-overlay__find-legend">
        Find: {preview.matchCount ?? layout.markers.length}
        {worldCount > 0 ? ` · ${worldCount} world` : ''}
        {invCount > 0 ? ` · ${invCount} inv` : ''}
      </div>
    </div>
  );
}

function SingleClickOverlay({
  layout,
  preview,
}: {
  layout: ClickLayout;
  preview: ActionClickPreview;
}) {
  const { selected, alternates } = layout;
  const matchNote =
    preview.matchCount != null && preview.matchCount > 1
      ? `${preview.matchCount} matches`
      : null;
  const title = [
    preview.label ?? preview.blockId,
    preview.clickClientXY
      ? `click ${preview.clickClientXY[0]},${preview.clickClientXY[1]}`
      : null,
    preview.screenXY ? `screen ${preview.screenXY[0]},${preview.screenXY[1]}` : null,
    preview.score != null ? `score ${preview.score.toFixed(2)}` : null,
    preview.slot ?? null,
    matchNote,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="action-click-overlay" aria-hidden>
      {alternates.map((alt, index) => (
        <div
          key={`alt-${index}-${alt.left}-${alt.top}`}
          className="action-click-overlay__marker action-click-overlay__marker--candidate"
          style={{ left: alt.left, top: alt.top }}
          title={
            alt.score != null
              ? `Alternate match · score ${alt.score.toFixed(2)}`
              : 'Alternate match'
          }
        >
          <span className="action-click-overlay__candidate-ring" />
        </div>
      ))}
      <div
        className="action-click-overlay__marker action-click-overlay__marker--selected"
        style={{ left: selected.left, top: selected.top }}
        title={title}
      >
        <span className="action-click-overlay__crosshair" />
        <span className="action-click-overlay__ring" />
        <span className="action-click-overlay__label">
          {preview.searchMode === 'playspace' ? 'Click (world)' : 'Click (inv)'}
        </span>
      </div>
    </div>
  );
}

export function ActionClickOverlay({ preview, imageRef }: ActionClickOverlayProps) {
  const computeLayout = useCallback(
    (img: HTMLImageElement) => (preview ? computeOverlayLayout(img, preview) : null),
    [preview],
  );
  const layout = useImageAnchoredLayout<OverlayLayout>(imageRef, computeLayout, [preview]);

  if (!preview || !layout) return null;

  if (isFindLayout(layout)) {
    return <FindOverlay layout={layout} preview={preview} />;
  }

  if (isUseOnLayout(layout)) {
    return <UseOnOverlay layout={layout} preview={preview} />;
  }

  if (isClickLayout(layout)) {
    return <SingleClickOverlay layout={layout} preview={preview} />;
  }

  return null;
}
