import { useCallback, useEffect, useMemo, useState } from 'react';
import type { BotArgDef, BotManifestEntry, BotRunInfo } from '../../shared/bots';
import './BotsTab.css';
import './Panel.css';

function isRunning(run: BotRunInfo | null): boolean {
  if (!run) return false;
  return run.state === 'running' || run.state === 'paused' || run.state === 'starting' || run.state === 'stopping';
}

/** Manifest bots launched as ``python -m …`` (not spec-driven agents). */
function isPythonModuleBot(bot: BotManifestEntry): boolean {
  return Boolean(bot.moduleArgv?.length) && !bot.deprecated;
}

function defaultArgValues(bot: BotManifestEntry): Record<string, number | string | boolean> {
  const out: Record<string, number | string | boolean> = {};
  for (const arg of bot.args ?? []) {
    if (arg.default !== undefined) {
      out[arg.name] = arg.default;
    }
  }
  return out;
}

function launchLabel(bot: BotManifestEntry): string {
  if (bot.moduleArgv?.length) {
    return `python ${bot.moduleArgv.join(' ')}`;
  }
  if (bot.scriptArgv?.length) {
    return `python ${bot.scriptArgv.join(' ')}`;
  }
  return bot.id;
}

type PythonBotsTabProps = {
  /** When set, highlight the bot matching the active run. */
  activeBotId?: string | null;
};

export function PythonBotsTab({ activeBotId }: PythonBotsTabProps) {
  const [bots, setBots] = useState<BotManifestEntry[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [argValues, setArgValues] = useState<Record<string, number | string | boolean>>({});
  const [run, setRun] = useState<BotRunInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pythonBots = useMemo(() => bots.filter(isPythonModuleBot), [bots]);
  const selected = pythonBots.find((b) => b.id === selectedId) ?? pythonBots[0] ?? null;
  const active = isRunning(run);
  const runIsSelected = active && run?.botId === selected?.id;

  useEffect(() => {
    let cancelled = false;
    window.exodia
      .listBots()
      .then((entries) => {
        if (cancelled) return;
        const modules = entries.filter(isPythonModuleBot);
        setBots(entries);
        setSelectedId((current) => {
          if (current && modules.some((b) => b.id === current)) return current;
          if (activeBotId && modules.some((b) => b.id === activeBotId)) return activeBotId;
          return modules[0]?.id ?? null;
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeBotId]);

  useEffect(() => {
    window.exodia.getBotRun().then(setRun);
    const unsubRun = window.exodia.onBotRunUpdate(setRun);
    return unsubRun;
  }, []);

  useEffect(() => {
    if (!selected) return;
    setArgValues(defaultArgValues(selected));
  }, [selected?.id]);

  const handleSelect = useCallback(
    (bot: BotManifestEntry) => {
      if (active) return;
      setSelectedId(bot.id);
      setError(null);
    },
    [active],
  );

  const handleArgChange = (arg: BotArgDef, raw: string) => {
    setArgValues((prev) => {
      const next = { ...prev };
      if (arg.type === 'number') {
        const n = Number(raw);
        next[arg.name] = Number.isFinite(n) ? n : 0;
      } else if (arg.type === 'boolean') {
        next[arg.name] = raw === 'true';
      } else {
        next[arg.name] = raw;
      }
      return next;
    });
  };

  const handleStart = async () => {
    if (!selected || active) return;
    setBusy(true);
    setError(null);
    try {
      const result = await window.exodia.startBot({
        botId: selected.id,
        argValues,
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
          Python FSM bots from <code>bots.manifest.json</code>. Requires calibrated client rect
          {pythonBots.some((b) => b.requiresStream) ? ' and perception stream.' : '.'}
        </p>
      </div>

      {loadError && <p className="bots-tab__error">{loadError}</p>}

      <ul className="bots-tab__list">
        {pythonBots.length === 0 && !loadError && (
          <li className="bots-tab__empty">No Python module bots in the manifest.</li>
        )}
        {pythonBots.map((bot) => (
          <li key={bot.id}>
            <button
              type="button"
              className={`bots-tab__item${selected?.id === bot.id ? ' bots-tab__item--selected' : ''}${active && run?.botId !== bot.id ? ' bots-tab__item--locked' : ''}`}
              onClick={() => handleSelect(bot)}
              disabled={active && run?.botId !== bot.id}
            >
              <span className="bots-tab__title">{bot.title}</span>
              <span className="bots-tab__note" title={launchLabel(bot)}>
                {launchLabel(bot)}
                {bot.requiresStream ? ' · stream' : ''}
              </span>
              {active && run?.botId === bot.id && (
                <span className={`bots-tab__state${run.state === 'paused' ? ' bots-tab__state--paused' : ''}${run.state === 'stopping' ? ' bots-tab__state--stopping' : ''}`}>
                  {run.state}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="bots-tab__preview">
          <h3 className="bots-tab__preview-title">{selected.title}</h3>
          <pre className="bots-tab__preview-body">
            {selected.note ? `${selected.note}\n\n` : ''}
            {launchLabel(selected)}
            {selected.defaultArgv.length > 0 ? `\nDefault args: ${selected.defaultArgv.join(' ')}` : ''}
          </pre>
        </div>
      )}

      <div className="bots-tab__controls">
        {selected && (selected.args?.length ?? 0) > 0 && !runIsSelected && (
          <div className="bots-tab__args">
            {selected.args!.map((arg) => (
              <label key={arg.name} className="bots-tab__arg">
                <span>{arg.label ?? arg.name}</span>
                {arg.type === 'boolean' ? (
                  <select
                    value={String(argValues[arg.name] ?? arg.default ?? false)}
                    onChange={(e) => handleArgChange(arg, e.target.value)}
                    disabled={active}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input
                    type={arg.type === 'number' ? 'number' : 'text'}
                    value={String(argValues[arg.name] ?? arg.default ?? '')}
                    onChange={(e) => handleArgChange(arg, e.target.value)}
                    disabled={active}
                  />
                )}
              </label>
            ))}
          </div>
        )}

        <div className="bots-tab__actions">
          {!runIsSelected && (
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={handleStart}
              disabled={busy || !selected || active}
              title={active ? 'Stop the running bot first' : undefined}
            >
              {busy ? 'Starting…' : `Start ${selected?.title ?? 'bot'}`}
            </button>
          )}
          {runIsSelected && (
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
        {runIsSelected && run && (
          <p className="bots-tab__meta">
            {run.botTitle} · pid {run.pid ?? '—'}
            {run.startedAt ? ` · started ${new Date(run.startedAt).toLocaleTimeString()}` : ''}
          </p>
        )}
      </div>
    </div>
  );
}
