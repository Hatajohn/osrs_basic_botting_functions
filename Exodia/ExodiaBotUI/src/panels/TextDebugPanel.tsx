import type { StreamMeta } from '../../shared/ipc';
import { TextDebugOverlay } from '../components/TextDebugOverlay';
import { PanelHeader } from '../components/PanelHeader';
import './Panel.css';

type TextDebugPanelProps = {
  streamMeta?: StreamMeta | null;
  streamPortUp?: boolean;
};

export function TextDebugPanel({ streamMeta, streamPortUp }: TextDebugPanelProps) {
  return (
    <section className="panel panel--text-debug">
      <PanelHeader title="Text" />
      <div className="panel__body panel__body--flush">
        <TextDebugOverlay streamMeta={streamMeta} streamPortUp={streamPortUp} />
      </div>
    </section>
  );
}
