import { useCallback, useEffect, useState } from 'react';
import type { BotManifestEntry, BotRunInfo } from '../../shared/bots';
import './BotsTab.css';
import './Panel.css';

type ArgValues = Record<string, number | string | boolean>;

function defaultArgValues(bot: BotManifestEntry): ArgValues {
  const values: ArgValues = {};
  for (const arg of bot.args ?? []) {
    if (arg.default !== undefined) {
      values[arg.name] = arg.default;
    }
  }
  return values;
}

function isRunning(run: BotRunInfo | null): boolean {
  if (!run) return false;
  return run.state === 'running' || run.state === 'paused' || run.state === 'starting' || run.state === 'stopping';
}

export function BotsTab() {
  const [bots, setBots] = useState<BotManifestEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [argValues, setArgValues] = useState<ArgValues>({});
  const [run, setRun] = useState<BotRunInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = bots.find((b) => b.id === selectedId) ?? null;
  const active = isRunning(run);

  const loadBots = useCallback(async () => {
    const list = await window.exodia.listBots();
    setBots(list);
    if (list.length > 0 && !selectedId) {
      setSelectedId(list[0].id);
      setArgValues(defaultArgValues(list[0]));
    }
  }, [selectedId]);

  useEffect(() => {
    loadBots();
    window.exodia.getBotRun().then(setRun);
    const unsubRun = window.exodia.onBotRunUpdate(setRun);
    return unsubRun;
  }, [loadBots]);

  const selectBot = (bot: BotManifestEntry) => {
    setSelectedId(bot.id);
    setArgValues(defaultArgValues(bot));
    setError(null);
  };

  const updateArg = (name: string, type: string, raw: string) => {
    setArgValues((prev) => {
      const next = { ...prev };
      if (type === 'number') {
        const n = Number(raw);
        next[name] = Number.isFinite(n) ? n : 0;
      } else if (type === 'boolean') {
        next[name] = raw === 'true';
      } else {
        next[name] = raw;
      }
      return next;
    });
  };

  const handleStart = async () => {
    if (!selected || active) return;
    setBusy(true);
    setError(null);
    try {
      const result = await window.exodia.startBot({ botId: selected.id, argValues });
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
      <ul className="bots-tab__list">
        {bots.length === 0 && <li className="bots-tab__empty">No bots in manifest.</li>}
        {bots.map((bot) => (
          <li key={bot.id}>
            <button
              type="button"
              className={`bots-tab__item${selectedId === bot.id ? ' bots-tab__item--selected' : ''}${run?.botId === bot.id && active ? ' bots-tab__item--active' : ''}`}
              onClick={() => selectBot(bot)}
              disabled={active && run?.botId !== bot.id}
            >
              <span className="bots-tab__title">{bot.title}</span>
              {bot.note && <span className="bots-tab__note">{bot.note}</span>}
              {run?.botId === bot.id && active && (
                <span className={`bots-tab__state bots-tab__state--${run.state}`}>{run.state}</span>
              )}
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="bots-tab__controls">
          {(selected.args ?? []).length > 0 && (
            <div className="bots-tab__args">
              {selected.args!.map((arg) => (
                <label key={arg.name} className="bots-tab__arg">
                  <span>{arg.label ?? arg.name}</span>
                  {arg.type === 'boolean' ? (
                    <input
                      type="checkbox"
                      checked={Boolean(argValues[arg.name])}
                      onChange={(e) => updateArg(arg.name, arg.type, String(e.target.checked))}
                      disabled={active}
                    />
                  ) : (
                    <input
                      type={arg.type === 'number' ? 'number' : 'text'}
                      value={String(argValues[arg.name] ?? '')}
                      onChange={(e) => updateArg(arg.name, arg.type, e.target.value)}
                      disabled={active}
                    />
                  )}
                </label>
              ))}
            </div>
          )}

          <div className="bots-tab__actions">
            {!active && (
              <button type="button" className="btn btn--primary btn--sm" onClick={handleStart} disabled={busy}>
                {busy ? 'Starting…' : 'Start'}
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
              pid {run.pid ?? '—'}
              {run.startedAt ? ` · started ${new Date(run.startedAt).toLocaleTimeString()}` : ''}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
