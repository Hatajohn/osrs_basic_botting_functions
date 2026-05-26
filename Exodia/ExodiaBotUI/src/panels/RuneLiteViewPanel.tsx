import type { DebugFrameMode, DebugFrameResult } from '../../shared/ipc';
import './Panel.css';

type RuneLiteViewPanelProps = {
  imageDataUrl?: string;
  result?: DebugFrameResult | null;
  loading: boolean;
  calibrating: boolean;
  debugMode: DebugFrameMode;
  onRefresh: () => void;
  onCalibrate: () => void;
  previewLive?: boolean;
  onTogglePreviewLive?: (live: boolean) => void;
  botRunning?: boolean;
};

function formatMode(mode: DebugFrameMode): string {
  switch (mode) {
    case 'inventory_identify':
      return 'Inventory identify';
    case 'raw_client':
      return 'Raw client';
    case 'inventory_grid':
      return 'Grid only';
    default:
      return mode;
  }
}

function formatTime(ts?: number): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleTimeString();
}

export function RuneLiteViewPanel({
  imageDataUrl,
  result,
  loading,
  calibrating,
  debugMode,
  onRefresh,
  onCalibrate,
  previewLive = false,
  onTogglePreviewLive,
  botRunning = false,
}: RuneLiteViewPanelProps) {
  const hasImage = Boolean(imageDataUrl);
  const error = result && !result.ok ? result.error : undefined;
  const hint = result && !result.ok ? result.hint : undefined;
  const busy = loading || calibrating;
  const modeLabel = previewLive && botRunning ? 'Live preview' : formatMode(debugMode);

  return (
    <section className="panel panel--runelite">
      <header className="panel__header">
        <h2 className="panel__title">RuneLite view</h2>
        <div className="panel__header-actions">
          <span className={`panel__badge${previewLive && botRunning ? ' panel__badge--live' : ''}`}>
            {previewLive && botRunning ? 'Live' : 'Debug'}
          </span>
          {botRunning && onTogglePreviewLive && (
            <button
              type="button"
              className={`btn btn--sm${previewLive ? ' btn--active' : ''}`}
              onClick={() => onTogglePreviewLive(!previewLive)}
              title="Toggle between live MJPEG preview and manual debug refresh"
            >
              {previewLive ? 'Debug frame' : 'Live preview'}
            </button>
          )}
          <button
            type="button"
            className="btn btn--sm"
            onClick={onCalibrate}
            disabled={busy}
            title="Run calibrate_client_rect.py — drag a box around the RuneLite window"
          >
            {calibrating ? 'Calibrating…' : 'Calibrate'}
          </button>
          <button
            type="button"
            className="btn btn--sm"
            onClick={onRefresh}
            disabled={busy || (previewLive && botRunning)}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>
      <div className="panel__body panel__runelite-body">
        {loading && !hasImage && (
          <div className="panel__placeholder">
            <p>Capturing client and running inventory detect…</p>
          </div>
        )}
        {!loading && !hasImage && !error && (
          <div className="panel__placeholder">
            <p>
              {previewLive && botRunning
                ? 'Waiting for live preview from the bot stream…'
                : 'Click Refresh to capture the RuneLite client and show inventory overlays.'}
            </p>
            {!previewLive && (
              <p className="panel__hint">Requires client_rect.json and a visible RuneLite window.</p>
            )}
          </div>
        )}
        {error && !previewLive && (
          <div className="panel__error">
            <strong>{error}</strong>
            {hint && <p className="panel__hint">{hint}</p>}
            {!calibrating && (
              <button type="button" className="btn btn--sm panel__error-action" onClick={onCalibrate}>
                Calibrate client rect
              </button>
            )}
          </div>
        )}
        {hasImage && (
          <div className="panel__image-wrap">
            <img
              className="panel__debug-image"
              src={imageDataUrl}
              alt={previewLive && botRunning ? 'RuneLite live preview' : 'RuneLite debug frame'}
              draggable={false}
            />
          </div>
        )}
      </div>
      <footer className="panel__footer panel__footer--stats">
        <span>Mode: {modeLabel}</span>
        {!previewLive && result?.ok && result.occupied != null && <span>Occupied: {result.occupied}</span>}
        {!previewLive && result?.ok && result.unknown != null && <span>?: {result.unknown}</span>}
        {!previewLive && result?.ok && result.tmpCount != null && <span>tmp: {result.tmpCount}</span>}
        <span>Last refresh: {formatTime(result?.refreshedAt)}</span>
      </footer>
    </section>
  );
}
