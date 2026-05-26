import type { DebugFrameResult } from '../../shared/ipc';
import './Panel.css';

type BotTasksPanelProps = {
  debugResult?: DebugFrameResult | null;
  loading: boolean;
};

function formatMode(mode?: string): string {
  if (!mode) return '—';
  switch (mode) {
    case 'inventory_identify':
      return 'inventory identify';
    case 'raw_client':
      return 'raw client';
    case 'inventory_grid':
      return 'grid only';
    default:
      return mode;
  }
}

export function BotTasksPanel({ debugResult, loading }: BotTasksPanelProps) {
  const hasStats = debugResult?.ok && debugResult.occupied != null;

  return (
    <section className="panel panel--tasks">
      <header className="panel__header">
        <h2 className="panel__title">Current bot tasks</h2>
      </header>
      <div className="panel__body panel__placeholder panel__placeholder--compact">
        {loading && <p>Refreshing debug frame…</p>}
        {!loading && !debugResult && (
          <p>No debug frame yet. Use Refresh in RuneLite view or View → Refresh debug frame (F5).</p>
        )}
        {!loading && debugResult && !debugResult.ok && (
          <p className="panel__error-inline">Last refresh failed: {debugResult.error ?? 'unknown error'}</p>
        )}
        {!loading && hasStats && (
          <div className="panel__task-summary">
            <p>
              Last debug refresh ({formatMode(debugResult?.mode)}): occupied={debugResult?.occupied}
              {debugResult?.unknown != null ? ` unknown=${debugResult.unknown}` : ''}
              {debugResult?.tmpCount != null ? ` tmp=${debugResult.tmpCount}` : ''}
            </p>
            <p className="panel__hint">Live bot status arrives in Phase 2.</p>
          </div>
        )}
        {!loading && debugResult?.ok && debugResult.mode === 'raw_client' && (
          <div className="panel__task-summary">
            <p>Last debug refresh: raw client capture (no inventory overlay).</p>
            <p className="panel__hint">Live bot status arrives in Phase 2.</p>
          </div>
        )}
      </div>
    </section>
  );
}
