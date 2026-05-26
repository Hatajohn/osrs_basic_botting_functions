import { useCallback, useEffect, useState } from 'react';
import type { BotSpecFile } from '../../shared/specs';
import { AGENT_BOT_ID } from '../../shared/specs';
import type { BotRunInfo } from '../../shared/bots';
import './BotsTab.css';
import './Panel.css';

type BotsTabProps = {
  specs: BotSpecFile[];
  selectedSpecPath: string | null;
  onSelectSpec: (path: string) => void;
  onRemoveSpec: (path: string) => void;
  onClearSpecs: () => void;
};

function isRunning(run: BotRunInfo | null): boolean {
  if (!run) return false;
  return run.state === 'running' || run.state === 'paused' || run.state === 'starting' || run.state === 'stopping';
}

export function BotsTab({
  specs,
  selectedSpecPath,
  onSelectSpec,
  onRemoveSpec,
  onClearSpecs,
}: BotsTabProps) {
  const [run, setRun] = useState<BotRunInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = specs.find((s) => s.path === selectedSpecPath) ?? specs[0] ?? null;
  const active = isRunning(run);

  useEffect(() => {
    window.exodia.getBotRun().then(setRun);
    const unsubRun = window.exodia.onBotRunUpdate(setRun);
    return unsubRun;
  }, []);

  const handleStart = async () => {
    if (specs.length === 0 || active) return;
    setBusy(true);
    setError(null);
    try {
      const result = await window.exodia.startBot({
        botId: AGENT_BOT_ID,
        specPaths: specs.map((s) => s.path),
      });
      if (!result.ok && result.error) {
        setError(result.error);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    if (!active) return;
    setBusy(true);
    setError(null);
    try {
      const result = await window.exodia.stopBot();
      if (!result.ok && result.error) {
        setError(result.error);
      }
    } finally {
      setBusy(false);
    }
  };

  const handlePause = async () => {
    if (!active || run?.state === 'paused') return;
    await window.exodia.sendBotRuntimeCommand('pause');
  };

  const handleResume = async () => {
    if (run?.state !== 'paused') return;
    await window.exodia.sendBotRuntimeCommand('resume');
  };

  return (
    <div className="bots-tab">
      <div className="bots-tab__header">
        <p className="bots-tab__hint">
          Loaded task specs for the agent. Choose markdown files in the Specs tab.
        </p>
        {specs.length > 0 && !active && (
          <button type="button" className="btn btn--sm" onClick={onClearSpecs}>
            Clear all
          </button>
        )}
      </div>

      <ul className="bots-tab__list">
        {specs.length === 0 && (
          <li className="bots-tab__empty">
            No specs loaded. Open the Specs tab and load a <code>.md</code> file.
          </li>
        )}
        {specs.map((spec) => (
          <li key={spec.path}>
            <button
              type="button"
              className={`bots-tab__item${selected?.path === spec.path ? ' bots-tab__item--selected' : ''}${active ? ' bots-tab__item--locked' : ''}`}
              onClick={() => onSelectSpec(spec.path)}
              disabled={active}
            >
              <span className="bots-tab__title">{spec.name}</span>
              <span className="bots-tab__note" title={spec.path}>
                {spec.path}
              </span>
              {!active && (
                <span
                  role="button"
                  tabIndex={0}
                  className="bots-tab__remove"
                  title="Remove spec"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemoveSpec(spec.path);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      e.stopPropagation();
                      onRemoveSpec(spec.path);
                    }
                  }}
                >
                  ×
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="bots-tab__preview">
          <h3 className="bots-tab__preview-title">{selected.name}</h3>
          <pre className="bots-tab__preview-body">{selected.content}</pre>
        </div>
      )}

      <div className="bots-tab__controls">
        <div className="bots-tab__actions">
          {!active && (
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={handleStart}
              disabled={busy || specs.length === 0}
              title={specs.length === 0 ? 'Load at least one spec first' : undefined}
            >
              {busy ? 'Starting…' : 'Start agent'}
            </button>
          )}
          {active && (
            <>
              {run?.state !== 'paused' && run?.runtimeCommands.includes('pause') && (
                <button type="button" className="btn btn--sm" onClick={handlePause} disabled={busy}>
                  Pause
                </button>
              )}
              {run?.state === 'paused' && run?.runtimeCommands.includes('resume') && (
                <button type="button" className="btn btn--sm" onClick={handleResume} disabled={busy}>
                  Resume
                </button>
              )}
              <button type="button" className="btn btn--sm" onClick={handleStop} disabled={busy}>
                {busy ? 'Stopping…' : 'Stop'}
              </button>
            </>
          )}
        </div>

        {error && <p className="bots-tab__error">{error}</p>}
        {active && run && (
          <p className="bots-tab__meta">
            {run.botTitle} · pid {run.pid ?? '—'}
            {run.startedAt ? ` · started ${new Date(run.startedAt).toLocaleTimeString()}` : ''}
          </p>
        )}
      </div>
    </div>
  );
}
