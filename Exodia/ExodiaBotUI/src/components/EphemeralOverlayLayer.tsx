import { ActionClickOverlay } from './ActionClickOverlay';
import type { OverlayAnnotationEntry } from '../hooks/useOverlayAnnotations';

type EphemeralOverlayLayerProps = {
  annotations: OverlayAnnotationEntry[];
};

/** Fading action/find/use-on markers stacked above the live stream base layer. */
export function EphemeralOverlayLayer({ annotations }: EphemeralOverlayLayerProps) {
  if (annotations.length === 0) return null;

  return (
    <>
      {annotations.map((entry) => (
        <div
          key={entry.id}
          className="ephemeral-overlay-layer__entry"
          style={{ opacity: entry.opacity }}
        >
          <ActionClickOverlay preview={entry.preview} />
        </div>
      ))}
    </>
  );
}
