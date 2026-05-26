import { useCallback, useEffect, useState } from 'react';
import type { FileEntry } from '../../shared/ipc';
import { BotsTab } from './BotsTab';
import './BotsTab.css';
import './ScriptsPanel.css';
import './Panel.css';

type ScriptsPanelProps = {
  onPathChange?: (path: string) => void;
};

type TabId = 'browse' | 'bots';

export function ScriptsPanel({ onPathChange }: ScriptsPanelProps) {
  const [tab, setTab] = useState<TabId>('bots');
  const [rootPath, setRootPath] = useState('');
  const [browsePath, setBrowsePath] = useState('');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  const loadDirectory = useCallback(async (dirPath: string) => {
    setLoading(true);
    setError(null);
    const result = await window.exodia.listDirectory(dirPath);
    setBrowsePath(result.path);
    setParentPath(result.parentPath);
    setEntries(result.entries);
    setError(result.error ?? null);
    setLoading(false);
    onPathChange?.(result.path);
  }, [onPathChange]);

  const loadRoot = useCallback(async () => {
    const { resolved } = await window.exodia.getSettings();
    setRootPath(resolved.scriptsFolder);
    await loadDirectory(resolved.scriptsFolder);
  }, [loadDirectory]);

  useEffect(() => {
    if (tab === 'browse') {
      loadRoot();
    }
  }, [tab, loadRoot]);

  const chooseFolder = async () => {
    const result = await window.exodia.selectScriptsFolder();
    if (result.canceled || !result.path) return;
    setRootPath(result.path);
    setSelectedPath(null);
    await loadDirectory(result.path);
  };

  const openEntry = (entry: FileEntry) => {
    if (entry.kind === 'directory') {
      setSelectedPath(entry.path);
      loadDirectory(entry.path);
      return;
    }
    setSelectedPath(entry.path);
  };

  const goUp = () => {
    if (parentPath) loadDirectory(parentPath);
  };

  const canGoUp = parentPath !== null;

  return (
    <section className="panel panel--scripts">
      <header className="panel__header panel__header--stacked">
        <h2 className="panel__title">Scripts</h2>
        {tab === 'browse' && (
          <button type="button" className="btn btn--sm" onClick={chooseFolder}>
            Choose folder…
          </button>
        )}
      </header>

      <div className="scripts-panel__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'bots'}
          className={`scripts-panel__tab${tab === 'bots' ? ' scripts-panel__tab--active' : ''}`}
          onClick={() => setTab('bots')}
        >
          Bots
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'browse'}
          className={`scripts-panel__tab${tab === 'browse' ? ' scripts-panel__tab--active' : ''}`}
          onClick={() => setTab('browse')}
        >
          Browse
        </button>
      </div>

      <div className="panel__body scripts-panel scripts-panel__tab-body">
        {tab === 'bots' && <BotsTab />}
        {tab === 'browse' && (
          <>
            <p className="scripts-panel__path" title={browsePath || rootPath}>
              {browsePath || rootPath || 'No folder selected'}
            </p>

            {canGoUp && (
              <button type="button" className="file-tree__row file-tree__row--parent" onClick={goUp}>
                <span className="file-tree__icon">↩</span>
                <span className="file-tree__name">Parent folder</span>
              </button>
            )}

            <div className="file-tree">
              {loading && <p className="file-tree__status">Loading…</p>}
              {!loading && error && <p className="file-tree__error">{error}</p>}
              {!loading && !error && entries.length === 0 && (
                <p className="file-tree__status">Folder is empty.</p>
              )}
              {!loading &&
                !error &&
                entries.map((entry) => (
                  <button
                    key={entry.path}
                    type="button"
                    className={`file-tree__row${selectedPath === entry.path ? ' file-tree__row--selected' : ''}`}
                    onClick={() => openEntry(entry)}
                    onDoubleClick={() => entry.kind === 'directory' && openEntry(entry)}
                  >
                    <span className={`file-tree__icon file-tree__icon--${entry.kind}`}>
                      {entry.kind === 'directory' ? '▸' : '·'}
                    </span>
                    <span className="file-tree__name">{entry.name}</span>
                  </button>
                ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
