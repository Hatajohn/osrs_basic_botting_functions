import { useCallback, useEffect, useState } from 'react';
import type { FileEntry } from '../../shared/ipc';
import type { BotSpecFile } from '../../shared/specs';
import { PanelHeader } from '../components/PanelHeader';
import { BotsTab } from './BotsTab';
import { PythonBotsTab } from './PythonBotsTab';
import './BotsTab.css';
import './ScriptsPanel.css';
import './Panel.css';

type ScriptsPanelProps = {
  onPathChange?: (path: string) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  stripMode?: boolean;
};

type TabId = 'bots' | 'python' | 'specs';

export function ScriptsPanel({
  onPathChange,
  collapsed = false,
  onToggleCollapse,
  stripMode = false,
}: ScriptsPanelProps) {
  const [tab, setTab] = useState<TabId>('bots');
  const [rootPath, setRootPath] = useState('');
  const [browsePath, setBrowsePath] = useState('');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loadedSpecs, setLoadedSpecs] = useState<BotSpecFile[]>([]);
  const [selectedSpecPath, setSelectedSpecPath] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadDirectory = useCallback(async (dirPath: string) => {
    setLoading(true);
    setError(null);
    const result = await window.exodia.listDirectory(dirPath, { markdownOnly: true });
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
    if (tab === 'specs') {
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

  const loadSpecFromEntry = useCallback(async (entry: FileEntry) => {
    if (entry.kind !== 'file') return;
    setLoadError(null);
    const result = await window.exodia.readTextFile(entry.path);
    if (!result.ok || !result.content) {
      setLoadError(result.error ?? 'Failed to read spec file');
      return;
    }

    const spec: BotSpecFile = {
      path: result.path,
      name: result.name ?? entry.name,
      content: result.content,
      loadedAt: Date.now(),
    };

    setLoadedSpecs((prev) => {
      const idx = prev.findIndex((s) => s.path === spec.path);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = spec;
        return next;
      }
      return [...prev, spec];
    });
    setSelectedSpecPath(spec.path);
    setTab('bots');
  }, []);

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

  const removeSpec = (path: string) => {
    setLoadedSpecs((prev) => prev.filter((s) => s.path !== path));
    setSelectedSpecPath((current) => (current === path ? null : current));
  };

  const clearSpecs = () => {
    setLoadedSpecs([]);
    setSelectedSpecPath(null);
  };

  const canGoUp = parentPath !== null;
  const selectedEntry = entries.find((e) => e.path === selectedPath) ?? null;
  const canLoadSelected = selectedEntry?.kind === 'file';

  return (
    <section className={`panel panel--scripts${collapsed ? ' panel--collapsed-header' : ''}${stripMode ? ' panel--collapsed-strip' : ''}`}>
      <PanelHeader
        title="Scripts"
        minimizable
        collapsed={collapsed}
        onToggleCollapse={onToggleCollapse}
        strip={stripMode ? 'vertical' : 'none'}
        actions={
          !collapsed && tab === 'specs' ? (
            <button type="button" className="btn btn--sm" onClick={chooseFolder}>
              Choose folder…
            </button>
          ) : undefined
        }
      />

      {!collapsed && (
        <>
      <div className="scripts-panel__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'bots'}
          className={`scripts-panel__tab${tab === 'bots' ? ' scripts-panel__tab--active' : ''}`}
          onClick={() => setTab('bots')}
        >
          Bots
          {loadedSpecs.length > 0 && (
            <span className="scripts-panel__tab-badge">{loadedSpecs.length}</span>
          )}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'python'}
          className={`scripts-panel__tab${tab === 'python' ? ' scripts-panel__tab--active' : ''}`}
          onClick={() => setTab('python')}
        >
          Python
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'specs'}
          className={`scripts-panel__tab${tab === 'specs' ? ' scripts-panel__tab--active' : ''}`}
          onClick={() => setTab('specs')}
        >
          Specs
        </button>
      </div>

      <div className="panel__body scripts-panel scripts-panel__tab-body">
        {tab === 'bots' && (
          <BotsTab
            specs={loadedSpecs}
            selectedSpecPath={selectedSpecPath}
            onSelectSpec={setSelectedSpecPath}
            onRemoveSpec={removeSpec}
            onClearSpecs={clearSpecs}
          />
        )}
        {tab === 'python' && <PythonBotsTab />}
        {tab === 'specs' && (
          <>
            <p className="scripts-panel__path" title={browsePath || rootPath}>
              {browsePath || rootPath || 'No folder selected'}
            </p>

            {canLoadSelected && (
              <div className="scripts-panel__load-row">
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  onClick={() => selectedEntry && loadSpecFromEntry(selectedEntry)}
                >
                  Load into Bots
                </button>
              </div>
            )}

            {canGoUp && (
              <button type="button" className="file-tree__row file-tree__row--parent" onClick={goUp}>
                <span className="file-tree__icon">↩</span>
                <span className="file-tree__name">Parent folder</span>
              </button>
            )}

            <div className="file-tree">
              {loading && <p className="file-tree__status">Loading…</p>}
              {!loading && error && <p className="file-tree__error">{error}</p>}
              {!loading && loadError && <p className="file-tree__error">{loadError}</p>}
              {!loading && !error && entries.length === 0 && (
                <p className="file-tree__status">No markdown files in this folder.</p>
              )}
              {!loading &&
                !error &&
                entries.map((entry) => (
                  <button
                    key={entry.path}
                    type="button"
                    className={`file-tree__row${selectedPath === entry.path ? ' file-tree__row--selected' : ''}${loadedSpecs.some((s) => s.path === entry.path) ? ' file-tree__row--loaded' : ''}`}
                    onClick={() => openEntry(entry)}
                    onDoubleClick={() => {
                      if (entry.kind === 'directory') {
                        openEntry(entry);
                      } else {
                        void loadSpecFromEntry(entry);
                      }
                    }}
                  >
                    <span className={`file-tree__icon file-tree__icon--${entry.kind}`}>
                      {entry.kind === 'directory' ? '▸' : '◆'}
                    </span>
                    <span className="file-tree__name">{entry.name}</span>
                  </button>
                ))}
            </div>
          </>
        )}
      </div>
        </>
      )}
    </section>
  );
}
