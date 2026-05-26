import { LogConsole, type LogEntry } from '../components/LogConsole';
import './Panel.css';

type LogPanelProps = {
  entries: LogEntry[];
  onClear: () => void;
};

export function LogPanel({ entries, onClear }: LogPanelProps) {
  return (
    <section className="panel panel--log">
      <header className="panel__header">
        <h2 className="panel__title">Log</h2>
      </header>
      <div className="panel__body">
        <LogConsole entries={entries} onClear={onClear} />
      </div>
    </section>
  );
}
