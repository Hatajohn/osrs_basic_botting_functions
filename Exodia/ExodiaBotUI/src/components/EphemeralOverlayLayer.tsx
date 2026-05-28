import type { RefObject } from 'react';
import { ActionClickOverlay } from './ActionClickOverlay';
import type { OverlayAnnotationEntry } from '../hooks/useOverlayAnnotations';

type EphemeralOverlayLayerProps = {
  annotations: OverlayAnnotationEntry[];
  imageRef: RefObject<HTMLImageElement | null>;
};

/** Fading action/find/use-on markers stacked above the live stream base layer. */
export function EphemeralOverlayLayer({ annotations, imageRef }: EphemeralOverlayLayerProps) {
  if (annotations.length === 0) return null;

  return (
    <>
      {annotations.map((entry) => (
        <div
          key={entry.id}
          className="ephemeral-overlay-layer__entry"
          style={{ opacity: entry.opacity }}
        >
          <ActionClickOverlay preview={entry.preview} imageRef={imageRef} />
        </div>
      ))}
    </>
  );
}
