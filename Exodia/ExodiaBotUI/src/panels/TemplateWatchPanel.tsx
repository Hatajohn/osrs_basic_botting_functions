import { useCallback, useEffect, useState } from 'react';
import type { StreamMeta, TemplateWatchEntry, TemplateWatchlist, TemplateWatchRegion } from '../../shared/ipc';
import { worldScanStem } from '../../shared/templateWatchAliases';
import './TemplateWatchPanel.css';
import './Panel.css';

type TemplateWatchPanelProps = {
  streamMeta?: StreamMeta | null;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
};

function formatSlotSummary(slots: number[][] | undefined): string {
  if (!slots?.length) return '—';
  return slots.map(([r, c]) => `${r + 1},${c + 1}`).join(' · ');
}

function formatInvStatus(source?: string, slotCount?: number): string {
  switch (source) {
    case 'template':
      return slotCount ? 'match' : 'no match';
    case 'labels':
      return 'via labels';
    case 'missing_template':
      return 'missing PNG';
    case 'none':
      return 'no match';
    default:
      return '—';
  }
}

function statForTemplate(meta: StreamMeta | null | undefined, template: string) {
  const stats = meta?.perception?.world?.template_stats ?? [];
  return stats.find((s) => s.template === template);
}

function worldStatForEntry(meta: StreamMeta | null | undefined, entry: TemplateWatchEntry) {
  if (!entry.world) return undefined;
  return statForTemplate(meta, worldScanStem(entry.template));
}

function invWatchForTemplate(meta: StreamMeta | null | undefined, template: string) {
  const watch = meta?.perception?.inventory?.inventory_watch ?? [];
  return watch.find((w) => w.template === template);
}

function enabledCount(entries: TemplateWatchEntry[]): number {
  return entries.filter((e) => e.world || e.inventory).length;
}

export function TemplateWatchPanel({
  streamMeta,
  collapsed = false,
  onToggleCollapsed,
}: TemplateWatchPanelProps) {
  const [watchlist, setWatchlist] = useState<TemplateWatchlist>({ version: 1, entries: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalog, setCatalog] = useState<Array<{ id: string; label: string; templateFile?: string | null }>>([]);

  const persist = useCallback(async (next: TemplateWatchlist) => {
    setSaving(true);
    setError(undefined);
    try {
      const saved = await window.exodia.setTemplateWatchlist(next);
      setWatchlist(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save watchlist');
    } finally {
      setSaving(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void window.exodia.getTemplateWatchlist().then((data) => {
      if (!cancelled) {
        setWatchlist(data);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const updateEntries = useCallback(
    (entries: TemplateWatchEntry[]) => {
      const next = { version: 1 as const, entries };
      setWatchlist(next);
      void persist(next);
    },
    [persist],
  );

  const toggleRegion = (id: string, region: 'world' | 'inventory') => {
    updateEntries(
      watchlist.entries.map((e) =>
        e.id === id ? { ...e, [region]: !e[region] } : e,
      ),
    );
  };

  const removeEntry = (id: string) => {
    updateEntries(watchlist.entries.filter((e) => e.id !== id));
  };

  const addEntry = (template: string, region: TemplateWatchRegion) => {
    const stem = template.replace(/\.png$/i, '');
    if (!stem.trim()) return;

    const existing = watchlist.entries.find((e) => e.template === stem);
    if (existing) {
      updateEntries(
        watchlist.entries.map((e) =>
          e.template === stem ? { ...e, [region]: true } : e,
        ),
      );
      return;
    }

    const id = `w${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
    updateEntries([
      ...watchlist.entries,
      { id, template: stem, world: region === 'world', inventory: region === 'inventory' },
    ]);
  };

  const openCatalog = async () => {
    setCatalogOpen(true);
    const result = await window.exodia.listItemCatalog();
    if (!result.ok) {
      setError(result.error ?? 'Catalog unavailable');
      setCatalogOpen(false);
      return;
    }
    const items = [...result.named, ...result.fingerprints].map((entry) => ({
      id: entry.id,
      label: entry.displayName,
      templateFile: entry.templateFile,
    }));
    setCatalog(items);
  };

  const pickFile = async (region: TemplateWatchRegion) => {
    const picked = await window.exodia.selectTemplateFile();
    if (picked.canceled || !picked.template) return;
    addEntry(picked.template, region);
  };

  if (collapsed) {
    return (
      <div className="template-watch template-watch--collapsed">
        <button type="button" className="template-watch__collapse-btn" onClick={onToggleCollapsed}>
          Template watch ({enabledCount(watchlist.entries)} enabled)
        </button>
      </div>
    );
  }

  return (
    <section className="template-watch panel">
      <header className="panel__header template-watch__header">
        <h3 className="panel__title">Template watch</h3>
        <div className="panel__header-actions">
          {saving && <span className="template-watch__status">Saving…</span>}
          <button type="button" className="btn btn--sm" onClick={() => void openCatalog()}>
            + Catalog
          </button>
          <button type="button" className="btn btn--sm" onClick={() => void pickFile('world')}>
            + World file
          </button>
          <button type="button" className="btn btn--sm" onClick={() => void pickFile('inventory')}>
            + Inv file
          </button>
          {onToggleCollapsed && (
            <button type="button" className="btn btn--sm btn--icon" onClick={onToggleCollapsed} title="Collapse">
              ▾
            </button>
          )}
        </div>
      </header>
      <div className="panel__body template-watch__body">
        {loading && <p className="template-watch__empty">Loading…</p>}
        {!loading && error && <p className="panel__error">{error}</p>}
        {!loading && watchlist.entries.length === 0 && (
          <p className="template-watch__empty">
            Add templates once, then toggle world and inventory matching independently.
            Inventory matching requires items/&lt;name&gt;.png under items/ or images/.
          </p>
        )}
        {!loading && watchlist.entries.length > 0 && (
          <table className="template-watch__table">
            <thead>
              <tr>
                <th title="Match in playspace">World</th>
                <th title="Match in inventory">Inv</th>
                <th>Template</th>
                <th>Hits / slots</th>
                <th>Score</th>
                <th>Status</th>
                <th aria-label="Remove" />
              </tr>
            </thead>
            <tbody>
              {watchlist.entries.map((entry) => {
                const worldStat = worldStatForEntry(streamMeta, entry);
                const invWatch = invWatchForTemplate(streamMeta, entry.template);
                const hitParts: string[] = [];
                if (entry.world) {
                  hitParts.push(`w:${worldStat?.hits ?? 0}`);
                }
                if (entry.inventory) {
                  hitParts.push(`i:${formatSlotSummary(invWatch?.slots)}`);
                }
                const hitLabel = hitParts.length > 0 ? hitParts.join(' · ') : '—';
                const scoreParts: string[] = [];
                if (entry.world && worldStat?.best_score != null) {
                  scoreParts.push(`w:${worldStat.best_score.toFixed(2)}`);
                }
                if (entry.inventory && invWatch?.best_score != null) {
                  scoreParts.push(`i:${invWatch.best_score.toFixed(2)}`);
                }
                const scoreLabel = scoreParts.length > 0 ? scoreParts.join(' · ') : '—';
                const statusParts: string[] = [];
                if (entry.world) {
                  statusParts.push(
                    worldStat && (worldStat.hits ?? 0) > 0 ? 'world: match' : 'world: —',
                  );
                }
                if (entry.inventory) {
                  statusParts.push(
                    `inv: ${formatInvStatus(invWatch?.source, invWatch?.slots?.length)}`,
                  );
                }
                const statusLabel = statusParts.length > 0 ? statusParts.join(' · ') : 'off';
                const inactive = !entry.world && !entry.inventory;
                return (
                  <tr key={entry.id} className={inactive ? 'template-watch__row--disabled' : ''}>
                    <td className="template-watch__check">
                      <input
                        type="checkbox"
                        checked={entry.world}
                        onChange={() => toggleRegion(entry.id, 'world')}
                        aria-label={`World match ${entry.template}`}
                      />
                    </td>
                    <td className="template-watch__check">
                      <input
                        type="checkbox"
                        checked={entry.inventory}
                        onChange={() => toggleRegion(entry.id, 'inventory')}
                        aria-label={`Inventory match ${entry.template}`}
                      />
                    </td>
                    <td className="template-watch__template" title={entry.template}>
                      {entry.template}
                    </td>
                    <td>{hitLabel}</td>
                    <td>{scoreLabel}</td>
                    <td className="template-watch__status">{statusLabel}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--sm btn--icon"
                        onClick={() => removeEntry(entry.id)}
                        title="Remove"
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {catalogOpen && (
          <div className="template-watch__catalog">
            <div className="template-watch__catalog-header">
              <span>Pick from item catalog</span>
              <button type="button" className="btn btn--sm" onClick={() => setCatalogOpen(false)}>
                Close
              </button>
            </div>
            <ul className="template-watch__catalog-list">
              {catalog.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="template-watch__catalog-item"
                    onClick={() => {
                      const tpl = item.templateFile ?? item.id;
                      addEntry(tpl, 'inventory');
                      setCatalogOpen(false);
                    }}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
