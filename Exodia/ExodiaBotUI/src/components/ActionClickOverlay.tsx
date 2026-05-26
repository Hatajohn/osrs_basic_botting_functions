import { useCallback, useEffect, useState } from 'react';
import type { ActionClickPreview } from '../../shared/ipc';
import './ActionClickOverlay.css';

type PointLayout = {
  left: number;
  top: number;
  score?: number;
  searchMode?: 'inventory' | 'playspace';
};

type UseOnLayout = {
  from: PointLayout;
  to: PointLayout;
};

type ClickLayout = {
  selected: PointLayout;
  alternates: PointLayout[];
};

type FindLayout = {
  markers: PointLayout[];
};

type ActionClickOverlayProps = {
  preview: ActionClickPreview | null;
  imageRef: React.RefObject<HTMLImageElement | null>;
};

function clientXYToLayout(
  img: HTMLImageElement,
  preview: ActionClickPreview,
  clientXY: [number, number],
  extra?: Pick<PointLayout, 'score' | 'searchMode'>,
): PointLayout | null {
  const { frameWidth, frameHeight } = preview;
  if (frameWidth <= 0 || frameHeight <= 0) return null;

  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (nw <= 0 || nh <= 0) return null;

  const px = (clientXY[0] / frameWidth) * nw;
  const py = (clientXY[1] / frameHeight) * nh;

  const rect = img.getBoundingClientRect();
  const scaleX = rect.width / nw;
  const scaleY = rect.height / nh;

  const wrap = img.parentElement;
  if (!wrap) return null;
  const wrapRect = wrap.getBoundingClientRect();

  return {
    left: rect.left - wrapRect.left + px * scaleX,
    top: rect.top - wrapRect.top + py * scaleY,
    score: extra?.score,
    searchMode: extra?.searchMode,
  };
}

function computeClickLayout(img: HTMLImageElement, preview: ActionClickPreview): ClickLayout | null {
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

function computeFindLayout(img: HTMLImageElement, preview: ActionClickPreview): FindLayout | null {
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

function computeUseOnLayout(
  img: HTMLImageElement,
  preview: ActionClickPreview,
): UseOnLayout | null {
  if (!preview.fromClientXY || !preview.toClientXY) return null;
  const from = clientXYToLayout(img, preview, preview.fromClientXY);
  const to = clientXYToLayout(img, preview, preview.toClientXY);
  if (!from || !to) return null;
  return { from, to };
}

function useOverlayLayout(
  imageRef: React.RefObject<HTMLImageElement | null>,
  preview: ActionClickPreview | null,
): ClickLayout | UseOnLayout | FindLayout | null {
  const [layout, setLayout] = useState<ClickLayout | UseOnLayout | FindLayout | null>(null);

  const update = useCallback(() => {
    const img = imageRef.current;
    if (!img || !preview) {
      setLayout(null);
      return;
    }
    if (preview.previewMode === 'find') {
      setLayout(computeFindLayout(img, preview));
      return;
    }
    if (preview.previewMode === 'use_on' || (preview.fromClientXY && preview.toClientXY)) {
      setLayout(computeUseOnLayout(img, preview));
      return;
    }
    setLayout(computeClickLayout(img, preview));
  }, [imageRef, preview]);

  useEffect(() => {
    update();
    const img = imageRef.current;
    if (!img) return undefined;

    const ro = new ResizeObserver(() => update());
    ro.observe(img);
    if (img.parentElement) ro.observe(img.parentElement);

    return () => ro.disconnect();
  }, [imageRef, preview, update]);

  return layout;
}

function isUseOnLayout(layout: ClickLayout | UseOnLayout | FindLayout | null): layout is UseOnLayout {
  return layout != null && 'from' in layout && 'to' in layout;
}

function isClickLayout(layout: ClickLayout | UseOnLayout | FindLayout | null): layout is ClickLayout {
  return layout != null && 'selected' in layout;
}

function isFindLayout(layout: ClickLayout | UseOnLayout | FindLayout | null): layout is FindLayout {
  return layout != null && 'markers' in layout;
}

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
  const layout = useOverlayLayout(imageRef, preview);

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
