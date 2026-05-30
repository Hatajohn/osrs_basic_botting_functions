import { useCallback, useMemo, useState } from 'react';
import type { StreamMeta } from '../../shared/ipc';
import './PerceptionMetaJsonPanel.css';
import '../panels/Panel.css';

export type MetaJsonSlice = 'full' | 'perception' | 'inventory' | 'world';

type PerceptionMetaJsonPanelProps = {
  streamMeta?: StreamMeta | null;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
};

function metaSlice(meta: StreamMeta | null | undefined, slice: MetaJsonSlice): unknown {
  if (!meta) return null;
  switch (slice) {
    case 'full':
      return meta;
    case 'perception':
      return meta.perception ?? {};
    case 'inventory':
      return meta.perception?.inventory ?? {};
    case 'world':
      return meta.perception?.world ?? {};
  }
}

function sliceLabel(slice: MetaJsonSlice): string {
  switch (slice) {
    case 'full':
      return '/meta';
    case 'perception':
      return 'perception';
    case 'inventory':
      return 'inventory';
    case 'world':
      return 'world';
  }
}

export function PerceptionMetaJsonPanel({
  streamMeta,
  collapsed = false,
  onToggleCollapsed,
}: PerceptionMetaJsonPanelProps) {
  const [slice, setSlice] = useState<MetaJsonSlice>('full');
  const [copyHint, setCopyHint] = useState<string | undefined>();

  const payload = useMemo(() => metaSlice(streamMeta, slice), [streamMeta, slice]);
  const jsonText = useMemo(() => {
    if (payload == null) return '';
    try {
      return JSON.stringify(payload, null, 2);
    } catch {
      return String(payload);
    }
  }, [payload]);

  const copyJson = useCallback(async () => {
    if (!jsonText) return;
    try {
      await navigator.clipboard.writeText(jsonText);
      setCopyHint('Copied');
    } catch {
      setCopyHint('Copy failed');
    }
    window.setTimeout(() => setCopyHint(undefined), 1600);
  }, [jsonText]);

  const seq = streamMeta?.capture_seq;
  const trackCount = streamMeta?.perception?.world?.track_count;
  const hitCount = streamMeta?.perception?.world?.hit_count;

  if (collapsed) {
    return (
      <div className="meta-json meta-json--collapsed">
        <button type="button" className="meta-json__collapse-btn" onClick={onToggleCollapsed}>
          /meta JSON
          {seq != null ? ` · seq ${seq}` : ''}
          {trackCount != null ? ` · ${trackCount} track(s)` : ''}
        </button>
      </div>
    );
  }

  return (
    <section className="meta-json panel">
      <header className="panel__header meta-json__header">
        <h3 className="panel__title">/meta JSON</h3>
        <div className="panel__header-actions">
          {seq != null && <span className="meta-json__chip">seq {seq}</span>}
          {hitCount != null && <span className="meta-json__chip">{hitCount} hit(s)</span>}
          {trackCount != null && <span className="meta-json__chip">{trackCount} track(s)</span>}
          <div className="meta-json__slice-tabs" role="tablist" aria-label="Meta JSON slice">
            {(['full', 'perception', 'inventory', 'world'] as const).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={slice === key}
                className={`btn btn--sm${slice === key ? ' btn--active' : ''}`}
                onClick={() => setSlice(key)}
                title={`Show ${sliceLabel(key)} slice`}
              >
                {sliceLabel(key)}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => void copyJson()}
            disabled={!jsonText}
            title="Copy JSON to clipboard"
          >
            {copyHint ?? 'Copy'}
          </button>
          {onToggleCollapsed && (
            <button type="button" className="btn btn--sm btn--icon" onClick={onToggleCollapsed} title="Collapse">
              ▾
            </button>
          )}
        </div>
      </header>
      <div className="panel__body meta-json__body">
        {!streamMeta && (
          <p className="meta-json__empty">No /meta yet — calibrate and start the perception stream.</p>
        )}
        {streamMeta && !jsonText && (
          <p className="meta-json__empty">Selected slice is empty.</p>
        )}
        {jsonText && <pre className="meta-json__pre">{jsonText}</pre>}
      </div>
    </section>
  );
}
