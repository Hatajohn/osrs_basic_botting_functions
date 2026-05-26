import { useCallback, useEffect, useRef, useState } from 'react';
import type { LogLinePayload } from '../../shared/ipc';
import './LogConsole.css';

export type LogEntry = LogLinePayload;

type LogConsoleProps = {
  entries: LogEntry[];
  onClear?: () => void;
};

function formatTs(ts: number): string {
  return new Date(ts).toLocaleTimeString(undefined, { hour12: false });
}

export function LogConsole({ entries, onClear }: LogConsoleProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [entries, autoScroll]);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAutoScroll(atBottom);
  }, []);

  const handleCopy = async () => {
    const text = entries
      .map((e) => `[${formatTs(e.ts)}] ${e.line}`)
      .join('\n');
    await navigator.clipboard.writeText(text);
  };

  return (
    <div className="log-console">
      <div className="log-console__toolbar">
        <button type="button" className="btn btn--sm" onClick={handleCopy}>
          Copy
        </button>
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => onClear?.()}
        >
          Clear
        </button>
      </div>
      <div className="log-console__scroll" onScroll={handleScroll}>
        {entries.length === 0 ? (
          <p className="log-console__empty">Log output will appear here.</p>
        ) : (
          entries.map((entry, i) => (
            <div
              key={`${entry.ts}-${i}`}
              className={`log-console__line log-console__line--${entry.stream}`}
            >
              <span className="log-console__ts">{formatTs(entry.ts)}</span>
              <span className="log-console__text">{entry.line}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

/** Hook: subscribe to main-process log lines. */
export function useLogStream(): [LogEntry[], () => void, (entry: LogEntry) => void] {
  const [entries, setEntries] = useState<LogEntry[]>([]);

  useEffect(() => {
    if (!window.exodia?.onLogLine) {
      console.warn('Exodia preload API not available');
      return;
    }
    const unsub = window.exodia.onLogLine((payload) => {
      setEntries((prev) => [...prev, payload]);
    });
    return unsub;
  }, []);

  const clear = useCallback(() => setEntries([]), []);
  const append = useCallback((entry: LogEntry) => {
    setEntries((prev) => [...prev, entry]);
  }, []);

  return [entries, clear, append];
}
