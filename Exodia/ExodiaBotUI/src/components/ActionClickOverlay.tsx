import { useCallback, useEffect, useState } from 'react';
import type { ActionClickPreview } from '../../shared/ipc';
import './ActionClickOverlay.css';

type PointLayout = {
  left: number;
  top: number;
};

type UseOnLayout = {
  from: PointLayout;
  to: PointLayout;
};

type ActionClickOverlayProps = {
  preview: ActionClickPreview | null;
  imageRef: React.RefObject<HTMLImageElement | null>;
};

function clientXYToLayout(
  img: HTMLImageElement,
  preview: ActionClickPreview,
  clientXY: [number, number],
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
  };
}

function computeClickMarker(
  img: HTMLImageElement,
  preview: ActionClickPreview,
): PointLayout | null {
  if (!preview.clickClientXY) return null;
  return clientXYToLayout(img, preview, preview.clickClientXY);
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
): PointLayout | UseOnLayout | null {
  const [layout, setLayout] = useState<PointLayout | UseOnLayout | null>(null);

  const update = useCallback(() => {
    const img = imageRef.current;
    if (!img || !preview) {
      setLayout(null);
      return;
    }
    if (preview.previewMode === 'use_on' || (preview.fromClientXY && preview.toClientXY)) {
      setLayout(computeUseOnLayout(img, preview));
      return;
    }
    setLayout(computeClickMarker(img, preview));
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

function isUseOnLayout(layout: PointLayout | UseOnLayout | null): layout is UseOnLayout {
  return layout != null && 'from' in layout && 'to' in layout;
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

function SingleClickOverlay({
  marker,
  preview,
}: {
  marker: PointLayout;
  preview: ActionClickPreview;
}) {
  const title = [
    preview.label ?? preview.blockId,
    preview.clickClientXY
      ? `client ${preview.clickClientXY[0]},${preview.clickClientXY[1]}`
      : null,
    preview.screenXY ? `screen ${preview.screenXY[0]},${preview.screenXY[1]}` : null,
    preview.score != null ? `score ${preview.score.toFixed(2)}` : null,
    preview.slot ?? null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="action-click-overlay" aria-hidden>
      <div
        className="action-click-overlay__marker"
        style={{ left: marker.left, top: marker.top }}
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

  if (isUseOnLayout(layout)) {
    return <UseOnOverlay layout={layout} preview={preview} />;
  }

  return <SingleClickOverlay marker={layout} preview={preview} />;
}
