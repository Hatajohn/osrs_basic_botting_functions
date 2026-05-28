import type { BotRunInfo, RuntimeStatusPayload } from '../../shared/bots';
import type { DebugFrameResult } from '../../shared/ipc';
import './Panel.css';

type BotTasksPanelProps = {
  debugResult?: DebugFrameResult | null;
  loading: boolean;
  botRun?: BotRunInfo | null;
  runtimeStatus?: RuntimeStatusPayload | null;
  streamRunning?: boolean;
};

function formatUptime(startedAt: number | null, sessionUptimeS?: number): string {
  if (sessionUptimeS != null && sessionUptimeS >= 0) {
    const s = Math.floor(sessionUptimeS);
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return m > 0 ? `${m}m ${rem}s` : `${s}s`;
  }
  if (!startedAt) return '—';
  const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function chip(label: string, value: string | number | boolean | undefined | null): string | null {
  if (value === undefined || value === null || value === '') return null;
  return `${label}=${String(value)}`;
}

export function BotTasksPanel({
  debugResult,
  loading,
  botRun,
  runtimeStatus,
  streamRunning = false,
}: BotTasksPanelProps) {
  const hasActiveBot =
    botRun &&
    (botRun.state === 'running' ||
      botRun.state === 'paused' ||
      botRun.state === 'starting' ||
      botRun.state === 'stopping');

  const ctx = runtimeStatus?.context ?? {};
  const perception = runtimeStatus?.perception ?? {};
  const fsmState = (ctx.fsm_state as string | undefined) ?? runtimeStatus?.state;
  const chips = [
    chip('fsm', fsmState),
    chip('action', runtimeStatus?.last_action),
    chip('paused', runtimeStatus?.paused),
    chip('action_code', perception.action_code as number | undefined),
    chip('inv', perception.inventory_calibrated),
    chip('eel', ctx.eel_count as number | undefined),
    chip('cycles', ctx.cycles as number | undefined),
    chip('brain', ctx.brain as string | undefined),
    chip('tick', ctx.tick as number | undefined),
  ].filter(Boolean);

  const hasStats = debugResult?.ok && debugResult.occupied != null;

  return (
    <section className="panel panel--tasks">
      <header className="panel__header">
        <h2 className="panel__title">Current bot tasks</h2>
      </header>
      <div className="panel__body panel__placeholder panel__placeholder--compact">
        {hasActiveBot && (
          <div className="panel__task-summary">
            <p>
              <strong>{botRun!.botTitle}</strong>
              {' · '}
              <span className={`panel__state panel__state--${botRun!.state}`}>{botRun!.state}</span>
              {' · '}
              pid {botRun!.pid ?? '—'}
              {' · '}
              uptime {formatUptime(botRun!.startedAt, runtimeStatus?.session_uptime_s)}
            </p>
            {chips.length > 0 && (
              <p className="panel__chips">{chips.join(' · ')}</p>
            )}
            {!runtimeStatus && botRun!.state === 'running' && (
              <p className="panel__hint">Waiting for runtime_status.json…</p>
            )}
          </div>
        )}

        {!hasActiveBot && loading && (
          <p>{streamRunning ? 'Re-analyzing stream…' : 'Capturing debug frame…'}</p>
        )}
        {!hasActiveBot && !loading && !debugResult && (
          <p>
            No bot running. Start one from Scripts → Bots
            {streamRunning ? '.' : ', or calibrate to start the perception stream.'}
          </p>
        )}
        {!hasActiveBot && !loading && debugResult && !debugResult.ok && (
          <p className="panel__error-inline">Last refresh failed: {debugResult.error ?? 'unknown error'}</p>
        )}
        {!hasActiveBot && !loading && hasStats && (
          <div className="panel__task-summary">
            <p>
              Last debug refresh: occupied={debugResult?.occupied}
              {debugResult?.unknown != null ? ` unknown=${debugResult.unknown}` : ''}
              {debugResult?.tmpCount != null ? ` tmp=${debugResult.tmpCount}` : ''}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
