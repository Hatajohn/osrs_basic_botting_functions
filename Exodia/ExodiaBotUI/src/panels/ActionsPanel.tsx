import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  ActionBlockDef,
  ActionClickPreview,
  ItemCatalogEntry,
  RunSingleActionResult,
} from '../../shared/ipc';
import './ActionsPanel.css';
import './Panel.css';

type ActionsPanelProps = {
  botRunning?: boolean;
  onActionClickPreview?: (preview: ActionClickPreview | null) => void;
  onPrepareClickPreview?: () => Promise<void>;
};

const BLOCK_INV = 'click_template_inv';
const BLOCK_WORLD = 'click_template_world';
const BLOCK_USE_ON = 'use_item_id_on_item_id';

/** Fishing spot sprite (playspace); canonical copy in images/, source in captures/. */
const SPOT_TEMPLATE = 'osrs_infernalEel.png';
/** Inventory item icon in items/. */
const INV_TEMPLATE = 'infernal_eel.png';

function formatLastResult(result: RunSingleActionResult | null): string {
  if (!result) return '';
  if (!result.ok) {
    return `last: failed · ${result.blockId} · ${result.error ?? 'unknown error'}`;
  }
  const ms = result.durationMs != null ? `${result.durationMs}ms` : '—';
  return `last: ok · ${ms} · ${result.blockId}`;
}

function templateArgs(template: string, templatePath?: string): Record<string, string> {
  const args: Record<string, string> = { template: template.trim() };
  if (templatePath) {
    args.templatePath = templatePath;
  }
  return args;
}

function optionLabel(entry: ItemCatalogEntry): string {
  if (entry.kind === 'fingerprint' && entry.displayName !== entry.itemId) {
    return `${entry.displayName} (${entry.itemId})`;
  }
  return entry.displayName;
}

function ItemIdSelect({
  id,
  label,
  value,
  onChange,
  entries,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (itemId: string) => void;
  entries: { named: ItemCatalogEntry[]; fingerprints: ItemCatalogEntry[] };
  disabled: boolean;
}) {
  return (
    <label className="actions-panel__field" htmlFor={id}>
      <span className="actions-panel__label">{label}</span>
      <select
        id={id}
        className="actions-panel__select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        <option value="">— pick or type below —</option>
        {entries.named.length > 0 && (
          <optgroup label="Named items (items/*.png)">
            {entries.named.map((entry) => (
              <option key={entry.itemId} value={entry.itemId}>
                {optionLabel(entry)}
              </option>
            ))}
          </optgroup>
        )}
        {entries.fingerprints.length > 0 && (
          <optgroup label="Fingerprints (items/fingerprints)">
            {entries.fingerprints.map((entry) => (
              <option key={entry.itemId} value={entry.itemId}>
                {optionLabel(entry)}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </label>
  );
}

function withBlockLabel(
  preview: ActionClickPreview,
  block: ActionBlockDef | undefined,
  blockId: string,
): ActionClickPreview {
  return { ...preview, label: block?.label ?? blockId };
}

export function ActionsPanel({
  botRunning = false,
  onActionClickPreview,
  onPrepareClickPreview,
}: ActionsPanelProps) {
  const [template, setTemplate] = useState('');
  const [templatePath, setTemplatePath] = useState<string | undefined>();
  const [catalogPick, setCatalogPick] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [destId, setDestId] = useState('');
  const [named, setNamed] = useState<ItemCatalogEntry[]>([]);
  const [fingerprints, setFingerprints] = useState<ItemCatalogEntry[]>([]);
  const [matchHint, setMatchHint] = useState<string | null>(null);
  const [spotImagePath, setSpotImagePath] = useState('');
  const [invImagePath, setInvImagePath] = useState('');
  const [blocks, setBlocks] = useState<ActionBlockDef[]>([]);
  const [busy, setBusy] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<RunSingleActionResult | null>(null);

  const catalogEntries = useMemo(
    () => ({ named, fingerprints }),
    [named, fingerprints],
  );

  const allByItemId = useMemo(() => {
    const map = new Map<string, ItemCatalogEntry>();
    for (const entry of [...named, ...fingerprints]) {
      map.set(entry.itemId, entry);
    }
    return map;
  }, [named, fingerprints]);

  useEffect(() => {
    window.exodia.listActionBlocks().then(setBlocks).catch(() => setBlocks([]));
    window.exodia.listItemCatalog().then((result) => {
      if (result.ok) {
        setNamed(result.named);
        setFingerprints(result.fingerprints);
      }
    });
    window.exodia.getSettings().then(({ resolved }) => {
      const root = resolved.exodiaRoot;
      setSpotImagePath(`${root}/images/${SPOT_TEMPLATE}`);
      setInvImagePath(`${root}/items/${INV_TEMPLATE}`);
    });
  }, []);

  const setFishingSpotTemplate = () => {
    setValidationError(null);
    setTemplate(SPOT_TEMPLATE);
    setTemplatePath(spotImagePath || undefined);
    setCatalogPick('');
    setMatchHint('Fishing spot — use “Click template outside inventory”');
  };

  const setInventoryItemTemplate = () => {
    setValidationError(null);
    setTemplate(INV_TEMPLATE);
    setTemplatePath(invImagePath || undefined);
    setCatalogPick('');
    setMatchHint('Inventory item — use “Click template in inventory”');
  };

  const applyCatalogEntry = useCallback((entry: ItemCatalogEntry) => {
    setCatalogPick(entry.itemId);
    if (entry.templateFile) {
      setTemplate(entry.templateFile);
    }
    setTemplatePath(entry.templatePath ?? undefined);
    setMatchHint(`${entry.kind === 'fingerprint' ? 'Fingerprint' : 'Item'}: ${optionLabel(entry)}`);
  }, []);

  const blockById = useCallback(
    (id: string) => blocks.find((b) => b.id === id),
    [blocks],
  );

  const confirmInput = (blockId: string, detail: string): boolean => {
    const block = blockById(blockId);
    if (block?.sideEffects !== 'input') return true;
    return window.confirm(`Run input action?\n\n${detail}`);
  };

  const runAction = async (blockId: string, args: Record<string, string>) => {
    setValidationError(null);
    setLastResult(null);

    if (botRunning) {
      setValidationError('Stop the bot before running actions.');
      return;
    }

    const block = blockById(blockId);
    const label = block?.label ?? blockId;

    const isTemplateClick = blockId === BLOCK_INV || blockId === BLOCK_WORLD;

    if (blockId === BLOCK_USE_ON) {
      if (!sourceId.trim() || !destId.trim()) {
        setValidationError('Source and dest item IDs are required.');
        return;
      }

      setBusy(true);
      try {
        await onPrepareClickPreview?.();
        const dry = await window.exodia.runSingleAction({ blockId, args, dryRun: true });
        if (!dry.ok) {
          onActionClickPreview?.(null);
          setValidationError(dry.error ?? 'Could not preview use-on targets');
          return;
        }
        if (dry.clickPreview) {
          onActionClickPreview?.(withBlockLabel(dry.clickPreview, block, blockId));
        }

        const overlayNote = dry.clickPreview
          ? '\n\nArrow in RuneLite view: red “Use” → green “On”.'
          : '';
        if (
          !confirmInput(
            blockId,
            `${label}\n${sourceId.trim()} → ${destId.trim()}${overlayNote}`,
          )
        ) {
          onActionClickPreview?.(null);
          return;
        }

        const result = await window.exodia.runSingleAction({ blockId, args });
        setLastResult(result);
        if (result.ok && result.clickPreview) {
          onActionClickPreview?.(withBlockLabel(result.clickPreview, block, blockId));
        } else if (!result.ok) {
          onActionClickPreview?.(null);
          setValidationError(result.error ?? 'Action failed');
        }
      } finally {
        setBusy(false);
      }
      return;
    }

    if (isTemplateClick) {
      if (!template.trim()) {
        setValidationError('Template filename is required.');
        return;
      }

      setBusy(true);
      try {
        await onPrepareClickPreview?.();
        const dry = await window.exodia.runSingleAction({ blockId, args, dryRun: true });
        if (!dry.ok) {
          onActionClickPreview?.(null);
          setValidationError(dry.error ?? 'Could not preview click target');
          return;
        }
        if (dry.clickPreview) {
          onActionClickPreview?.(withBlockLabel(dry.clickPreview, block, blockId));
        }

        const catalogNote = catalogPick ? `\nCatalog: ${catalogPick}` : '';
        const overlayNote = dry.clickPreview
          ? '\n\nGreen crosshair in RuneLite view shows the planned click.'
          : '';
        if (
          !confirmInput(
            blockId,
            `${label}\nTemplate: ${template.trim()}${catalogNote}${overlayNote}`,
          )
        ) {
          onActionClickPreview?.(null);
          return;
        }

        const result = await window.exodia.runSingleAction({ blockId, args });
        setLastResult(result);
        if (result.ok && result.clickPreview) {
          onActionClickPreview?.(withBlockLabel(result.clickPreview, block, blockId));
        } else if (!result.ok) {
          onActionClickPreview?.(null);
          setValidationError(result.error ?? 'Action failed');
        }
      } finally {
        setBusy(false);
      }
      return;
    } else {
      onActionClickPreview?.(null);
      if (!template.trim()) {
        setValidationError('Template filename is required.');
        return;
      }
      const catalogNote = catalogPick ? `\nCatalog: ${catalogPick}` : '';
      if (!confirmInput(blockId, `${label}\nTemplate: ${template.trim()}${catalogNote}`)) return;
    }

    setBusy(true);
    try {
      const result = await window.exodia.runSingleAction({ blockId, args });
      setLastResult(result);
      if (!result.ok) {
        setValidationError(result.error ?? 'Action failed');
        onActionClickPreview?.(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const disabled = botRunning || busy;

  const browseTemplate = async () => {
    setValidationError(null);
    setMatchHint(null);
    const result = await window.exodia.selectTemplateFile();
    if (result.canceled) return;
    if (!result.ok) {
      setValidationError(result.error ?? 'Could not select template');
      return;
    }
    if (result.template) {
      setTemplate(result.template);
      setTemplatePath(result.templatePath);
      setCatalogPick('');
    }
    if (result.role === 'fishing_spot') {
      setMatchHint('Fishing spot — use “Click template outside inventory”');
      return;
    }
    if (result.role === 'inventory_item') {
      setMatchHint('Inventory item — use “Click template in inventory”');
      return;
    }
    if (result.path) {
      const resolved = await window.exodia.resolveTemplateItem(result.path);
      if (!resolved.ok) {
        setMatchHint(resolved.error ?? 'Catalog lookup failed');
        return;
      }
      if (resolved.matched && resolved.itemId) {
        const entry = allByItemId.get(resolved.itemId);
        if (entry) {
          applyCatalogEntry(entry);
        } else {
          setCatalogPick(resolved.itemId);
          if (resolved.templateFile) setTemplate(resolved.templateFile);
          if (resolved.templatePath) setTemplatePath(resolved.templatePath);
        }
        const score =
          resolved.score != null ? ` · score ${resolved.score.toFixed(2)}` : '';
        setMatchHint(
          `Matched catalog: ${resolved.displayName ?? resolved.itemId} (${resolved.itemId})${score}`,
        );
      } else {
        const parts: string[] = ['No catalog match — using file as raw template'];
        if (resolved.bestNamed && resolved.bestNamedScore != null) {
          parts.push(`nearest named: ${resolved.bestNamed} (${resolved.bestNamedScore.toFixed(2)})`);
        }
        setMatchHint(parts.join(' · '));
      }
    }
  };

  const onCatalogPick = (itemId: string) => {
    setCatalogPick(itemId);
    if (!itemId) return;
    const entry = allByItemId.get(itemId);
    if (entry) {
      applyCatalogEntry(entry);
    }
  };

  return (
    <section className="panel panel--actions">
      <header className="panel__header">
        <h2 className="panel__title">Actions</h2>
      </header>
      <div className="panel__body actions-panel__body">
        {botRunning && (
          <p className="actions-panel__hint actions-panel__hint--warn">
            Bot is running — actions are disabled.
          </p>
        )}

        <p className="actions-panel__hint">
          Infernal eel <strong>fishing spot</strong>: <code>{SPOT_TEMPLATE}</code> (
          <code>captures/{SPOT_TEMPLATE}</code> → <code>images/</code>). Inventory{' '}
          <strong>item</strong>: <code>{INV_TEMPLATE}</code> in <code>items/</code>. Same art, different
          buttons — world search ignores the inventory panel.
        </p>

        <div className="actions-panel__field">
          <span className="actions-panel__label">Template file</span>
          <div className="actions-panel__template-row">
            <input
              className="actions-panel__input"
              type="text"
              value={template}
              onChange={(e) => {
                setTemplate(e.target.value);
                setTemplatePath(undefined);
                setCatalogPick('');
                setMatchHint(null);
              }}
              placeholder={`world: ${SPOT_TEMPLATE} · inv: ${INV_TEMPLATE}`}
              disabled={disabled}
              spellCheck={false}
              title={templatePath ?? undefined}
            />
            <button
              type="button"
              className="btn btn--sm"
              disabled={disabled}
              onClick={browseTemplate}
            >
              Browse…
            </button>
          </div>
          <div className="actions-panel__preset-row">
            <button
              type="button"
              className="btn btn--sm"
              disabled={disabled}
              onClick={setFishingSpotTemplate}
            >
              Set fishing spot
            </button>
            <button
              type="button"
              className="btn btn--sm"
              disabled={disabled}
              onClick={setInventoryItemTemplate}
            >
              Set inv item
            </button>
          </div>
          {templatePath && (
            <span className="actions-panel__path-hint" title={templatePath}>
              {templatePath}
            </span>
          )}
          {matchHint && <span className="actions-panel__match-hint">{matchHint}</span>}
        </div>

        <label className="actions-panel__field">
          <span className="actions-panel__label">Pick from catalog</span>
          <select
            className="actions-panel__select"
            value={catalogPick}
            onChange={(e) => onCatalogPick(e.target.value)}
            disabled={disabled}
          >
            <option value="">— none —</option>
            {named.length > 0 && (
              <optgroup label="Named items">
                {named.map((entry) => (
                  <option key={entry.itemId} value={entry.itemId}>
                    {optionLabel(entry)}
                  </option>
                ))}
              </optgroup>
            )}
            {fingerprints.length > 0 && (
              <optgroup label="Fingerprints">
                {fingerprints.map((entry) => (
                  <option key={entry.itemId} value={entry.itemId}>
                    {optionLabel(entry)}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>

        <ItemIdSelect
          id="actions-source-pick"
          label="Source item (pick)"
          value={sourceId && allByItemId.has(sourceId) ? sourceId : ''}
          onChange={(itemId) => setSourceId(itemId)}
          entries={catalogEntries}
          disabled={disabled}
        />
        <label className="actions-panel__field">
          <span className="actions-panel__label">Source item ID</span>
          <input
            className="actions-panel__input"
            type="text"
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            placeholder="e.g. imcando_hammer or unknown:5982bb64"
            disabled={disabled}
            spellCheck={false}
          />
        </label>

        <ItemIdSelect
          id="actions-dest-pick"
          label="Dest item (pick)"
          value={destId && allByItemId.has(destId) ? destId : ''}
          onChange={(itemId) => setDestId(itemId)}
          entries={catalogEntries}
          disabled={disabled}
        />
        <label className="actions-panel__field">
          <span className="actions-panel__label">Dest item ID</span>
          <input
            className="actions-panel__input"
            type="text"
            value={destId}
            onChange={(e) => setDestId(e.target.value)}
            placeholder="e.g. infernal_eel"
            disabled={disabled}
            spellCheck={false}
          />
        </label>

        <div className="actions-panel__buttons">
          <button
            type="button"
            className="btn btn--sm btn--primary"
            disabled={disabled}
            onClick={() => runAction(BLOCK_INV, templateArgs(template, templatePath))}
          >
            Click template in inventory
          </button>
          <button
            type="button"
            className="btn btn--sm btn--primary"
            disabled={disabled}
            onClick={() => runAction(BLOCK_WORLD, templateArgs(template, templatePath))}
          >
            Click template outside inventory
          </button>
          <button
            type="button"
            className="btn btn--sm btn--primary"
            disabled={disabled}
            onClick={() =>
              runAction(BLOCK_USE_ON, {
                sourceId: sourceId.trim(),
                destId: destId.trim(),
              })
            }
          >
            Use item ID on item ID
          </button>
        </div>

        {validationError && (
          <p className="actions-panel__hint actions-panel__hint--warn">{validationError}</p>
        )}

        <p
          className={`actions-panel__footer ${
            lastResult?.ok ? 'actions-panel__footer--ok' : lastResult ? 'actions-panel__footer--error' : ''
          }`}
        >
          {busy ? 'Running…' : formatLastResult(lastResult)}
        </p>
      </div>
    </section>
  );
}
