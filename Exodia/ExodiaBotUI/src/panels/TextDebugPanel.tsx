import type { StreamMeta } from '../../shared/ipc';
import { TextDebugOverlay } from '../components/TextDebugOverlay';
import { PanelHeader } from '../components/PanelHeader';
import './Panel.css';

type TextDebugPanelProps = {
  streamMeta?: StreamMeta | null;
  streamPortUp?: boolean;
  showTextHighlights?: boolean;
  onToggleTextHighlights?: (show: boolean) => void;
};

export function TextDebugPanel({
  streamMeta,
  streamPortUp,
  showTextHighlights,
  onToggleTextHighlights,
}: TextDebugPanelProps) {
  return (
    <section className="panel panel--text-debug">
      <PanelHeader title="Text" />
      <div className="panel__body panel__body--flush">
        <TextDebugOverlay
          streamMeta={streamMeta}
          streamPortUp={streamPortUp}
          showTextHighlights={showTextHighlights}
          onToggleTextHighlights={onToggleTextHighlights}
        />
      </div>
    </section>
  );
}
