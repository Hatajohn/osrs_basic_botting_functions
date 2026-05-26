import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  ActionBlockDef,
  ActionClickPreview,
  ItemCatalogEntry,
  MatchCandidatePreview,
  RunSingleActionResult,
} from '../../shared/ipc';
import './ActionsPanel.css';
import './Panel.css';

const DEFAULT_WORLD_CROP = 80;

type ActionsPanelProps = {
  botRunning?: boolean;
  actionClickPreview?: ActionClickPreview | null;
  onActionClickPreview?: (preview: ActionClickPreview | null) => void;
  onPrepareClickPreview?: () => Promise<void>;
};

type ItemSlot = 'source' | 'dest';

const BLOCK_INV = 'click_template_inv';
const BLOCK_WORLD = 'click_template_world';
const BLOCK_USE_ON = 'use_item_id_on_item_id';

const SPOT_TEMPLATE = 'osrs_infernalEel.png';
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

function withBlockLabel(
  preview: ActionClickPreview,
  block: ActionBlockDef | undefined,
  blockId: string,
  labelOverride?: string,
): ActionClickPreview {
  return { ...preview, label: labelOverride ?? block?.label ?? blockId };
}

function collectFindCandidates(
  preview: ActionClickPreview | undefined,
  searchMode: 'playspace' | 'inventory',
): MatchCandidatePreview[] {
  if (!preview) return [];
  if (preview.matchCandidates?.length) {
    return preview.matchCandidates.map((c) => ({
      ...c,
      selected: false,
      searchMode,
    }));
  }
  if (preview.clickClientXY) {
    return [
      {
        clickClientXY: preview.clickClientXY,
        score: preview.score,
        selected: false,
        searchMode,
      },
    ];
  }
  return [];
}

function mergeFindPreview(
  worldDry: RunSingleActionResult,
  invDry: RunSingleActionResult,
): ActionClickPreview | null {
  const frameWidth =
    worldDry.clickPreview?.frameWidth ?? invDry.clickPreview?.frameWidth ?? 0;
  const frameHeight =
    worldDry.clickPreview?.frameHeight ?? invDry.clickPreview?.frameHeight ?? 0;
  if (frameWidth <= 0 || frameHeight <= 0) return null;

  const candidates = [
    ...collectFindCandidates(worldDry.clickPreview, 'playspace'),
    ...collectFindCandidates(invDry.clickPreview, 'inventory'),
  ];
  if (candidates.length === 0) return null;

  return {
    blockId: 'find_template',
    previewMode: 'find',
    label: 'Find',
    frameWidth,
    frameHeight,
    matchCandidates: candidates,
    matchCount: candidates.length,
  };
}

function ItemCombobox({
  id,
  label,
  value,
  onChange,
  onClear,
  catalogOptions,
  disabled,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (itemId: string) => void;
  onClear: () => void;
  catalogOptions: ItemCatalogEntry[];
  disabled: boolean;
  placeholder?: string;
}) {
  const listId = `${id}-options`;
  return (
    <label className="actions-panel__field" htmlFor={id}>
      <span className="actions-panel__label">{label}</span>
      <div className="actions-panel__combo-row">
        <input
          id={id}
          className="actions-panel__input actions-panel__combo-input"
          type="text"
          list={listId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          spellCheck={false}
          autoComplete="off"
        />
        <button
          type="button"
          className="actions-panel__clear"
          disabled={disabled || !value}
          onClick={onClear}
          aria-label={`Clear ${label}`}
          title="Clear"
        >
          ×
        </button>
        <datalist id={listId}>
          {catalogOptions.map((entry) => (
            <option key={entry.itemId} value={entry.itemId} label={optionLabel(entry)} />
          ))}
        </datalist>
      </div>
    </label>
  );
}

function TemplateClickGroup({
  template,
  templatePath,
  matchHint,
  disabled,
  onTemplateChange,
  onBrowse,
  onPresetSpot,
  onPresetInv,
  onWorld,
  onInventory,
  onFind,
}: {
  template: string;
  templatePath?: string;
  matchHint: string | null;
  disabled: boolean;
  onTemplateChange: (value: string) => void;
  onBrowse: () => void;
  onPresetSpot: () => void;
  onPresetInv: () => void;
  onWorld: () => void;
  onInventory: () => void;
  onFind: () => void;
}) {
  return (
    <div className="actions-panel__template-block">
      <div className="actions-panel__field">
        <span className="actions-panel__label">Template file</span>
        <div className="actions-panel__template-row">
          <input
            className="actions-panel__input"
            type="text"
            value={template}
            onChange={(e) => onTemplateChange(e.target.value)}
            placeholder={`world: ${SPOT_TEMPLATE} · inv: ${INV_TEMPLATE}`}
            disabled={disabled}
            spellCheck={false}
            title={templatePath ?? undefined}
          />
          <button type="button" className="btn btn--sm" disabled={disabled} onClick={onBrowse}>
            Browse…
          </button>
        </div>
        <div className="actions-panel__preset-row">
          <button type="button" className="btn btn--sm" disabled={disabled} onClick={onPresetSpot}>
            Fishing spot
          </button>
          <button type="button" className="btn btn--sm" disabled={disabled} onClick={onPresetInv}>
            Inv item
          </button>
        </div>
        {templatePath && (
          <span className="actions-panel__path-hint" title={templatePath}>
            {templatePath}
          </span>
        )}
        {matchHint && <span className="actions-panel__match-hint">{matchHint}</span>}
      </div>
      <div className="actions-panel__button-group">
        <span className="actions-panel__button-group-label">Click template</span>
        <div className="actions-panel__button-group-actions actions-panel__button-group-actions--row">
          <button
            type="button"
            className="btn btn--sm btn--primary"
            disabled={disabled}
            onClick={onWorld}
          >
            World
          </button>
          <button
            type="button"
            className="btn btn--sm btn--primary"
            disabled={disabled}
            onClick={onInventory}
          >
            Inventory
          </button>
          <button type="button" className="btn btn--sm" disabled={disabled} onClick={onFind} title="Locate on screenshot only (no click)">
            Find
          </button>
        </div>
      </div>
    </div>
  );
}

export function ActionsPanel({
  botRunning = false,
  actionClickPreview = null,
  onActionClickPreview,
  onPrepareClickPreview,
}: ActionsPanelProps) {
  const [sourceId, setSourceId] = useState('');
  const [destId, setDestId] = useState('');
  const [sourceTemplate, setSourceTemplate] = useState('');
  const [sourceTemplatePath, setSourceTemplatePath] = useState<string | undefined>();
  const [destTemplate, setDestTemplate] = useState('');
  const [destTemplatePath, setDestTemplatePath] = useState<string | undefined>();
  const [sourceMatchHint, setSourceMatchHint] = useState<string | null>(null);
  const [destMatchHint, setDestMatchHint] = useState<string | null>(null);
  const [named, setNamed] = useState<ItemCatalogEntry[]>([]);
  const [fingerprints, setFingerprints] = useState<ItemCatalogEntry[]>([]);
  const [spotImagePath, setSpotImagePath] = useState('');
  const [invImagePath, setInvImagePath] = useState('');
  const [blocks, setBlocks] = useState<ActionBlockDef[]>([]);
  const [busy, setBusy] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<RunSingleActionResult | null>(null);
  const [saveName, setSaveName] = useState('');
  const [saveDest, setSaveDest] = useState<'items' | 'images'>('items');
  const [saveSlotRow, setSaveSlotRow] = useState('0');
  const [saveSlotCol, setSaveSlotCol] = useState('0');
  const [saveRectX, setSaveRectX] = useState('');
  const [saveRectY, setSaveRectY] = useState('');
  const [saveRectW, setSaveRectW] = useState(String(DEFAULT_WORLD_CROP));
  const [saveRectH, setSaveRectH] = useState(String(DEFAULT_WORLD_CROP));
  const [saveOverwrite, setSaveOverwrite] = useState(false);
  const [saveLinkSlot, setSaveLinkSlot] = useState<'none' | 'source' | 'dest'>('source');
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const catalogOptions = useMemo(
    () => [...named, ...fingerprints],
    [named, fingerprints],
  );

  const allByItemId = useMemo(() => {
    const map = new Map<string, ItemCatalogEntry>();
    for (const entry of catalogOptions) {
      map.set(entry.itemId, entry);
    }
    return map;
  }, [catalogOptions]);

  const reloadCatalog = useCallback(async () => {
    const result = await window.exodia.listItemCatalog();
    if (result.ok) {
      setNamed(result.named);
      setFingerprints(result.fingerprints);
    }
  }, []);

  useEffect(() => {
    window.exodia.listActionBlocks().then(setBlocks).catch(() => setBlocks([]));
    reloadCatalog();
    window.exodia.getSettings().then(({ resolved }) => {
      const root = resolved.exodiaRoot;
      setSpotImagePath(`${root}/images/${SPOT_TEMPLATE}`);
      setInvImagePath(`${root}/items/${INV_TEMPLATE}`);
    });
  }, [reloadCatalog]);

  const applyCatalogToSlot = useCallback(
    (slot: ItemSlot, itemId: string) => {
      const entry = allByItemId.get(itemId.trim());
      if (!entry) return;
      if (slot === 'source') {
        if (entry.templateFile) setSourceTemplate(entry.templateFile);
        setSourceTemplatePath(entry.templatePath ?? undefined);
        setSourceMatchHint(`${entry.kind === 'fingerprint' ? 'Fingerprint' : 'Item'}: ${optionLabel(entry)}`);
      } else {
        if (entry.templateFile) setDestTemplate(entry.templateFile);
        setDestTemplatePath(entry.templatePath ?? undefined);
        setDestMatchHint(`${entry.kind === 'fingerprint' ? 'Fingerprint' : 'Item'}: ${optionLabel(entry)}`);
      }
    },
    [allByItemId],
  );

  const handleItemChange = (slot: ItemSlot, itemId: string) => {
    if (slot === 'source') {
      setSourceId(itemId);
      if (!itemId.trim()) setSourceMatchHint(null);
    } else {
      setDestId(itemId);
      if (!itemId.trim()) setDestMatchHint(null);
    }
    if (allByItemId.has(itemId.trim())) {
      applyCatalogToSlot(slot, itemId);
    }
  };

  const clearItem = (slot: ItemSlot) => {
    if (slot === 'source') {
      setSourceId('');
      setSourceTemplate('');
      setSourceTemplatePath(undefined);
      setSourceMatchHint(null);
    } else {
      setDestId('');
      setDestTemplate('');
      setDestTemplatePath(undefined);
      setDestMatchHint(null);
    }
  };

  const setSlotPreset = (slot: ItemSlot, kind: 'spot' | 'inv') => {
    setValidationError(null);
    if (kind === 'spot') {
      if (slot === 'source') {
        setSourceTemplate(SPOT_TEMPLATE);
        setSourceTemplatePath(spotImagePath || undefined);
        setSourceMatchHint('Fishing spot template');
      } else {
        setDestTemplate(SPOT_TEMPLATE);
        setDestTemplatePath(spotImagePath || undefined);
        setDestMatchHint('Fishing spot template');
      }
    } else if (slot === 'source') {
      setSourceTemplate(INV_TEMPLATE);
      setSourceTemplatePath(invImagePath || undefined);
      setSourceMatchHint('Inventory item template');
    } else {
      setDestTemplate(INV_TEMPLATE);
      setDestTemplatePath(invImagePath || undefined);
      setDestMatchHint('Inventory item template');
    }
  };

  const blockById = useCallback(
    (id: string) => blocks.find((b) => b.id === id),
    [blocks],
  );

  const confirmInput = (blockId: string, detail: string): boolean => {
    const block = blockById(blockId);
    if (block?.sideEffects !== 'input') return true;
    return window.confirm(`Run input action?\n\n${detail}`);
  };

  const runAction = async (
    blockId: string,
    args: Record<string, string>,
    templateCtx?: {
      template: string;
      templatePath?: string;
      itemLabel?: string;
      findOnly?: boolean;
      findLabel?: string;
    },
  ) => {
    setValidationError(null);
    setLastResult(null);

    if (botRunning) {
      setValidationError('Stop the bot before running actions.');
      return;
    }

    const block = blockById(blockId);
    const label = block?.label ?? blockId;
    const isTemplateClick = blockId === BLOCK_INV || blockId === BLOCK_WORLD;
    const template = templateCtx?.template ?? '';
    const templatePath = templateCtx?.templatePath;

    if (blockId === BLOCK_USE_ON) {
      if (!sourceId.trim() || !destId.trim()) {
        setValidationError('Item 1 and item 2 IDs are required.');
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
          ? '\n\nRuneLite view: red “Use” and green “On” markers on inventory slots.'
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

      const itemNote = templateCtx?.itemLabel ? `\nItem: ${templateCtx.itemLabel}` : '';
      setBusy(true);
      try {
        await onPrepareClickPreview?.();
        const dry = await window.exodia.runSingleAction({
          blockId,
          args: templateArgs(template, templatePath),
          dryRun: true,
        });
        if (!dry.ok) {
          onActionClickPreview?.(null);
          setValidationError(dry.error ?? 'Could not preview click target');
          return;
        }
        const previewLabel = templateCtx?.findLabel ?? block?.label ?? blockId;
        if (dry.clickPreview) {
          onActionClickPreview?.(withBlockLabel(dry.clickPreview, block, blockId, previewLabel));
        }

        if (templateCtx?.findOnly) {
          setLastResult(dry);
          if (!dry.ok) {
            onActionClickPreview?.(null);
            setValidationError(dry.error ?? 'Template not found on screenshot');
          }
          return;
        }

        const matchNote =
          dry.clickPreview?.matchCount != null && dry.clickPreview.matchCount > 1
            ? `\n${dry.clickPreview.matchCount} matches: amber = alternates, green crosshair = click.`
            : '';
        const overlayNote = dry.clickPreview
          ? `\n\nGreen crosshair in RuneLite view shows the planned click.${matchNote}`
          : '';
        if (
          !confirmInput(
            blockId,
            `${label}\nTemplate: ${template.trim()}${itemNote}${overlayNote}`,
          )
        ) {
          onActionClickPreview?.(null);
          return;
        }

        const result = await window.exodia.runSingleAction({
          blockId,
          args: templateArgs(template, templatePath),
        });
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
    }
  };

  const disabled = botRunning || busy;
  const saveDisabled = disabled || saveBusy;

  const fillSaveRectFromPreview = () => {
    const preview = actionClickPreview;
    if (!preview) {
      setSaveMessage('Run Find or a click preview first, or set crop manually.');
      return;
    }
    let cx: number | undefined;
    let cy: number | undefined;
    if (preview.previewMode === 'use_on') {
      if (saveLinkSlot === 'dest' && preview.toClientXY) {
        [cx, cy] = preview.toClientXY;
      } else if (preview.fromClientXY) {
        [cx, cy] = preview.fromClientXY;
      }
    } else if (preview.clickClientXY) {
      [cx, cy] = preview.clickClientXY;
    }
    if (cx == null || cy == null) {
      setSaveMessage('No client coordinates in the current preview.');
      return;
    }
    const w = Number(saveRectW) || DEFAULT_WORLD_CROP;
    const h = Number(saveRectH) || DEFAULT_WORLD_CROP;
    setSaveRectX(String(Math.round(cx - w / 2)));
    setSaveRectY(String(Math.round(cy - h / 2)));
    setSaveDest('images');
    setSaveMessage('Crop set from preview center (world / images).');
  };

  const applySavedTemplate = (result: {
    dest?: 'items' | 'images';
    itemId?: string;
    templateFile?: string;
    templatePath?: string;
  }) => {
    if (!result.itemId) return;
    const slot = saveLinkSlot;
    if (result.dest === 'items') {
      if (slot === 'source') handleItemChange('source', result.itemId);
      else if (slot === 'dest') handleItemChange('dest', result.itemId);
    } else if (result.dest === 'images' && result.templateFile) {
      if (slot === 'source') {
        setSourceTemplate(result.templateFile);
        setSourceTemplatePath(result.templatePath);
        setSourceMatchHint(`Saved world template: ${result.templateFile}`);
      } else if (slot === 'dest') {
        setDestTemplate(result.templateFile);
        setDestTemplatePath(result.templatePath);
        setDestMatchHint(`Saved world template: ${result.templateFile}`);
      }
    }
  };

  const runSaveTemplate = async (mode: 'inventory' | 'world' | 'import', sourcePath?: string) => {
    setSaveMessage(null);
    const name = saveName.trim();
    if (!name) {
      setSaveMessage('Template name is required (e.g. infernal_eel, osrs_my_spot).');
      return;
    }
    if (mode === 'inventory') {
      const row = Number.parseInt(saveSlotRow, 10);
      const col = Number.parseInt(saveSlotCol, 10);
      if (!Number.isFinite(row) || !Number.isFinite(col)) {
        setSaveMessage('Slot row and col must be numbers (0–6, 0–3).');
        return;
      }
    }
    if (mode === 'world') {
      const rect = [
        Number.parseInt(saveRectX, 10),
        Number.parseInt(saveRectY, 10),
        Number.parseInt(saveRectW, 10),
        Number.parseInt(saveRectH, 10),
      ];
      if (rect.some((n) => !Number.isFinite(n))) {
        setSaveMessage('Crop X, Y, W, H must be numbers.');
        return;
      }
    }

    setSaveBusy(true);
    try {
      const result = await window.exodia.saveTemplate({
        mode,
        name,
        dest: saveDest,
        overwrite: saveOverwrite,
        slot:
          mode === 'inventory'
            ? [Number.parseInt(saveSlotRow, 10), Number.parseInt(saveSlotCol, 10)]
            : undefined,
        rect:
          mode === 'world'
            ? [
                Number.parseInt(saveRectX, 10),
                Number.parseInt(saveRectY, 10),
                Number.parseInt(saveRectW, 10),
                Number.parseInt(saveRectH, 10),
              ]
            : undefined,
        sourcePath,
      });
      if (!result.ok) {
        const hint = result.hint ? ` — ${result.hint}` : '';
        setSaveMessage(`${result.error ?? 'Save failed'}${hint}`);
        return;
      }
      await reloadCatalog();
      applySavedTemplate(result);
      const where = result.dest === 'images' ? 'images/' : 'items/';
      setSaveMessage(`Saved ${result.templateFile ?? name} → ${where}`);
    } finally {
      setSaveBusy(false);
    }
  };

  const importTemplateFile = async () => {
    const picked = await window.exodia.selectTemplateFile();
    if (picked.canceled || !picked.ok || !picked.path) return;
    if (!saveName.trim() && picked.name) {
      setSaveName(picked.name.replace(/\.[^.]+$/, '').toLowerCase());
    }
    await runSaveTemplate('import', picked.path);
  };

  const browseTemplate = async (slot: ItemSlot) => {
    setValidationError(null);
    if (slot === 'source') setSourceMatchHint(null);
    else setDestMatchHint(null);

    const result = await window.exodia.selectTemplateFile();
    if (result.canceled) return;
    if (!result.ok) {
      setValidationError(result.error ?? 'Could not select template');
      return;
    }

    const setTemplate = slot === 'source' ? setSourceTemplate : setDestTemplate;
    const setTemplatePath = slot === 'source' ? setSourceTemplatePath : setDestTemplatePath;
    const setMatchHint = slot === 'source' ? setSourceMatchHint : setDestMatchHint;

    if (result.template) {
      setTemplate(result.template);
      setTemplatePath(result.templatePath);
    }
    if (result.role === 'fishing_spot') {
      setMatchHint('Fishing spot — use World');
      return;
    }
    if (result.role === 'inventory_item') {
      setMatchHint('Inventory item — use Inventory');
      return;
    }
    if (result.path) {
      const resolved = await window.exodia.resolveTemplateItem(result.path);
      if (!resolved.ok) {
        setMatchHint(resolved.error ?? 'Catalog lookup failed');
        return;
      }
      if (resolved.matched && resolved.itemId) {
        handleItemChange(slot, resolved.itemId);
        const score = resolved.score != null ? ` · score ${resolved.score.toFixed(2)}` : '';
        setMatchHint(
          `Matched: ${resolved.displayName ?? resolved.itemId} (${resolved.itemId})${score}`,
        );
      } else {
        const parts: string[] = ['No catalog match — raw template'];
        if (resolved.bestNamed && resolved.bestNamedScore != null) {
          parts.push(`nearest: ${resolved.bestNamed} (${resolved.bestNamedScore.toFixed(2)})`);
        }
        setMatchHint(parts.join(' · '));
      }
    }
  };

  const templateCtxForSlot = (slot: ItemSlot) => {
    const template = slot === 'source' ? sourceTemplate : destTemplate;
    const templatePath = slot === 'source' ? sourceTemplatePath : destTemplatePath;
    const itemLabel = slot === 'source' ? '1' : '2';
    const itemId = slot === 'source' ? sourceId : destId;
    return {
      template,
      templatePath,
      itemLabel: itemId.trim() ? `item ${itemLabel} (${itemId.trim()})` : `item ${itemLabel}`,
    };
  };

  const runTemplateClick = (slot: ItemSlot, blockId: string) => {
    const ctx = templateCtxForSlot(slot);
    runAction(blockId, templateArgs(ctx.template, ctx.templatePath), ctx);
  };

  const runTemplateFind = async (slot: ItemSlot) => {
    const ctx = templateCtxForSlot(slot);
    if (!ctx.template.trim()) {
      setValidationError('Template filename is required.');
      return;
    }

    setValidationError(null);
    setLastResult(null);
    if (botRunning) {
      setValidationError('Stop the bot before running actions.');
      return;
    }

    const args = templateArgs(ctx.template, ctx.templatePath);
    setBusy(true);
    try {
      await onPrepareClickPreview?.();
      // Main process allows one action at a time — run world then inv (not Promise.all).
      const worldDry = await window.exodia.runSingleAction({
        blockId: BLOCK_WORLD,
        args,
        dryRun: true,
      });
      const invDry = await window.exodia.runSingleAction({
        blockId: BLOCK_INV,
        args,
        dryRun: true,
      });

      const preview = mergeFindPreview(worldDry, invDry);
      if (!preview) {
        onActionClickPreview?.(null);
        const err = worldDry.error ?? invDry.error ?? 'template_not_found';
        setValidationError(
          `No matches in world or inventory (${err}). Open inventory for inv search.`,
        );
        setLastResult({ ok: false, blockId: 'find_template', error: err });
        return;
      }

      onActionClickPreview?.(preview);
      const worldN = preview.matchCandidates?.filter((c) => c.searchMode === 'playspace').length ?? 0;
      const invN = preview.matchCandidates?.filter((c) => c.searchMode === 'inventory').length ?? 0;
      setLastResult({
        ok: true,
        blockId: 'find_template',
        durationMs: (worldDry.durationMs ?? 0) + (invDry.durationMs ?? 0),
        clickPreview: preview,
        result: { worldMatches: worldN, invMatches: invN },
      });
    } finally {
      setBusy(false);
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
          Item IDs drive <strong>use 1 on 2</strong>. Templates should be the <strong>item shape</strong>{' '}
          (transparent PNG, tight crop). World/Find use shape match, not cyan markers.
        </p>

        <section className="actions-panel__slot">
          <ItemCombobox
            id="actions-item-1"
            label="Item 1"
            value={sourceId}
            onChange={(id) => handleItemChange('source', id)}
            onClear={() => clearItem('source')}
            catalogOptions={catalogOptions}
            disabled={disabled}
            placeholder="e.g. imcando_hammer"
          />
          <TemplateClickGroup
            template={sourceTemplate}
            templatePath={sourceTemplatePath}
            matchHint={sourceMatchHint}
            disabled={disabled}
            onTemplateChange={(v) => {
              setSourceTemplate(v);
              setSourceTemplatePath(undefined);
              setSourceMatchHint(null);
            }}
            onBrowse={() => browseTemplate('source')}
            onPresetSpot={() => setSlotPreset('source', 'spot')}
            onPresetInv={() => setSlotPreset('source', 'inv')}
            onWorld={() => runTemplateClick('source', BLOCK_WORLD)}
            onInventory={() => runTemplateClick('source', BLOCK_INV)}
            onFind={() => runTemplateFind('source')}
          />
        </section>

        <section className="actions-panel__slot">
          <ItemCombobox
            id="actions-item-2"
            label="Item 2"
            value={destId}
            onChange={(id) => handleItemChange('dest', id)}
            onClear={() => clearItem('dest')}
            catalogOptions={catalogOptions}
            disabled={disabled}
            placeholder="e.g. infernal_eel"
          />
          <TemplateClickGroup
            template={destTemplate}
            templatePath={destTemplatePath}
            matchHint={destMatchHint}
            disabled={disabled}
            onTemplateChange={(v) => {
              setDestTemplate(v);
              setDestTemplatePath(undefined);
              setDestMatchHint(null);
            }}
            onBrowse={() => browseTemplate('dest')}
            onPresetSpot={() => setSlotPreset('dest', 'spot')}
            onPresetInv={() => setSlotPreset('dest', 'inv')}
            onWorld={() => runTemplateClick('dest', BLOCK_WORLD)}
            onInventory={() => runTemplateClick('dest', BLOCK_INV)}
            onFind={() => runTemplateFind('dest')}
          />
        </section>

        <button
          type="button"
          className="btn btn--sm btn--primary actions-panel__use-on-btn"
          disabled={disabled}
          onClick={() =>
            runAction(BLOCK_USE_ON, {
              sourceId: sourceId.trim(),
              destId: destId.trim(),
            })
          }
        >
          Use 1 on 2
        </button>

        <section className="actions-panel__save-section">
          <span className="actions-panel__button-group-label">Save template</span>
          <p className="actions-panel__hint">
            Live capture → <code>items/</code> (inventory icons) or <code>images/</code> (world). Names
            become catalog entries and template filenames.
          </p>
          <label className="actions-panel__field">
            <span className="actions-panel__label">Template name</span>
            <input
              className="actions-panel__input"
              type="text"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="e.g. infernal_eel or osrs_my_spot"
              disabled={saveDisabled}
              spellCheck={false}
            />
          </label>
          <label className="actions-panel__field">
            <span className="actions-panel__label">Save to</span>
            <select
              className="actions-panel__select"
              value={saveDest}
              onChange={(e) => setSaveDest(e.target.value as 'items' | 'images')}
              disabled={saveDisabled}
            >
              <option value="items">items/ (inventory)</option>
              <option value="images">images/ (world)</option>
            </select>
          </label>
          {saveDest === 'items' ? (
            <div className="actions-panel__save-grid">
              <label className="actions-panel__field">
                <span className="actions-panel__label">Slot row</span>
                <input
                  className="actions-panel__input"
                  type="number"
                  min={0}
                  max={6}
                  value={saveSlotRow}
                  onChange={(e) => setSaveSlotRow(e.target.value)}
                  disabled={saveDisabled}
                />
              </label>
              <label className="actions-panel__field">
                <span className="actions-panel__label">Slot col</span>
                <input
                  className="actions-panel__input"
                  type="number"
                  min={0}
                  max={3}
                  value={saveSlotCol}
                  onChange={(e) => setSaveSlotCol(e.target.value)}
                  disabled={saveDisabled}
                />
              </label>
            </div>
          ) : (
            <div className="actions-panel__save-grid actions-panel__save-grid--4">
              <label className="actions-panel__field">
                <span className="actions-panel__label">X</span>
                <input
                  className="actions-panel__input"
                  type="number"
                  value={saveRectX}
                  onChange={(e) => setSaveRectX(e.target.value)}
                  disabled={saveDisabled}
                />
              </label>
              <label className="actions-panel__field">
                <span className="actions-panel__label">Y</span>
                <input
                  className="actions-panel__input"
                  type="number"
                  value={saveRectY}
                  onChange={(e) => setSaveRectY(e.target.value)}
                  disabled={saveDisabled}
                />
              </label>
              <label className="actions-panel__field">
                <span className="actions-panel__label">W</span>
                <input
                  className="actions-panel__input"
                  type="number"
                  min={16}
                  value={saveRectW}
                  onChange={(e) => setSaveRectW(e.target.value)}
                  disabled={saveDisabled}
                />
              </label>
              <label className="actions-panel__field">
                <span className="actions-panel__label">H</span>
                <input
                  className="actions-panel__input"
                  type="number"
                  min={16}
                  value={saveRectH}
                  onChange={(e) => setSaveRectH(e.target.value)}
                  disabled={saveDisabled}
                />
              </label>
            </div>
          )}
          <label className="actions-panel__field">
            <span className="actions-panel__label">Link saved template to</span>
            <select
              className="actions-panel__select"
              value={saveLinkSlot}
              onChange={(e) => setSaveLinkSlot(e.target.value as 'none' | 'source' | 'dest')}
              disabled={saveDisabled}
            >
              <option value="none">— none —</option>
              <option value="source">Item 1</option>
              <option value="dest">Item 2</option>
            </select>
          </label>
          <label className="actions-panel__checkbox">
            <input
              type="checkbox"
              checked={saveOverwrite}
              onChange={(e) => setSaveOverwrite(e.target.checked)}
              disabled={saveDisabled}
            />
            <span>Overwrite existing file</span>
          </label>
          <div className="actions-panel__save-actions">
            {saveDest === 'images' && (
              <button
                type="button"
                className="btn btn--sm"
                disabled={saveDisabled}
                onClick={fillSaveRectFromPreview}
              >
                Fill from preview
              </button>
            )}
            <button
              type="button"
              className="btn btn--sm btn--primary"
              disabled={saveDisabled}
              onClick={() => runSaveTemplate(saveDest === 'items' ? 'inventory' : 'world')}
            >
              {saveBusy ? 'Saving…' : 'Save from capture'}
            </button>
            <button
              type="button"
              className="btn btn--sm"
              disabled={saveDisabled}
              onClick={importTemplateFile}
            >
              Import file…
            </button>
          </div>
          {saveMessage && (
            <p
              className={`actions-panel__hint ${
                saveMessage.startsWith('Saved') ? 'actions-panel__match-hint' : 'actions-panel__hint--warn'
              }`}
            >
              {saveMessage}
            </p>
          )}
        </section>

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
