import { useRef } from 'react';
import { ActionClickOverlay } from '../components/ActionClickOverlay';
import type { ActionClickPreview, DebugFrameMode, DebugFrameResult, PerceptionMeta } from '../../shared/ipc';
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
  streamRunning?: boolean;
  streamStale?: boolean;
  streamRestarting?: boolean;
  onRestartStream?: () => Promise<unknown>;
  perception?: PerceptionMeta | null;
  actionClickPreview?: ActionClickPreview | null;
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
  streamRunning = false,
  streamStale = false,
  streamRestarting = false,
  onRestartStream,
  perception = null,
  actionClickPreview = null,
}: RuneLiteViewPanelProps) {
  const imageRef = useRef<HTMLImageElement>(null);
  const usingLiveStream = Boolean(streamRunning && !previewLive && !botRunning);
  const showStreamControls = Boolean(!previewLive && !botRunning && onRestartStream);
  const hasImage = Boolean(imageDataUrl);
  const error = result && !result.ok ? result.error : undefined;
  const hint = result && !result.ok ? result.hint : undefined;
  const busy = loading || calibrating;
  const modeLabel = previewLive && botRunning
    ? 'Live preview'
    : usingLiveStream
      ? 'Live stream'
      : formatMode(debugMode);

  return (
    <section className="panel panel--runelite">
      <header className="panel__header">
        <h2 className="panel__title">RuneLite view</h2>
        <div className="panel__header-actions">
          <span className={`panel__badge${previewLive && botRunning ? ' panel__badge--live' : usingLiveStream ? ' panel__badge--live' : streamStale ? ' panel__badge--warn' : ''}`}>
            {previewLive && botRunning ? 'Live' : usingLiveStream ? 'Stream' : streamStale ? 'Stream stale' : 'Debug'}
          </span>
          {showStreamControls && onRestartStream && (
            <button
              type="button"
              className="btn btn--sm"
              onClick={() => void onRestartStream()}
              disabled={busy || streamRestarting}
              title="Hard-reset perception stream: kill port zombies and spawn fresh capture (use after template actions)"
            >
              {streamRestarting ? 'Resetting…' : 'Hard reset stream'}
            </button>
          )}
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
            title={usingLiveStream ? 'Force full re-identify on next stream frame' : undefined}
          >
            {loading ? 'Refreshing…' : usingLiveStream ? 'Re-analyze' : 'Refresh'}
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
                : streamRestarting
                  ? 'Restarting perception stream…'
                : streamStale
                  ? 'Stream stopped responding — click Restart stream or run a template action (auto-restart may apply).'
                : streamRunning
                  ? 'Waiting for perception stream frames…'
                  : 'Click Refresh to capture the RuneLite client and show inventory overlays.'}
            </p>
            {!previewLive && !streamRunning && !streamStale && (
              <p className="panel__hint">Requires client_rect.json and a visible RuneLite window.</p>
            )}
          </div>
        )}
        {error && !previewLive && !usingLiveStream && (
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
          <div className="panel__image-wrap panel__image-wrap--with-overlay">
            <img
              ref={imageRef}
              className="panel__debug-image"
              src={imageDataUrl}
              alt={
                previewLive && botRunning
                  ? 'RuneLite live preview'
                  : usingLiveStream
                    ? 'RuneLite inventory overlay stream'
                    : 'RuneLite debug frame'
              }
              draggable={false}
            />
            {!previewLive && !usingLiveStream && (
              <ActionClickOverlay
                key={imageDataUrl ?? 'frame'}
                preview={actionClickPreview}
                imageRef={imageRef}
              />
            )}
          </div>
        )}
      </div>
      <footer className="panel__footer panel__footer--stats">
        <span>Mode: {modeLabel}</span>
        {usingLiveStream && perception?.occupied != null && (
          <span>Occupied: {perception.occupied}</span>
        )}
        {usingLiveStream && perception?.unknown != null && <span>?: {perception.unknown}</span>}
        {usingLiveStream && perception?.tmp_count != null && (
          <span>tmp: {perception.tmp_count}</span>
        )}
        {!usingLiveStream && !previewLive && result?.ok && result.occupied != null && (
          <span>Occupied: {result.occupied}</span>
        )}
        {!usingLiveStream && !previewLive && result?.ok && result.unknown != null && (
          <span>?: {result.unknown}</span>
        )}
        {!usingLiveStream && !previewLive && result?.ok && result.tmpCount != null && (
          <span>tmp: {result.tmpCount}</span>
        )}
        {usingLiveStream && perception?.vision_fps != null && (
          <span>Vision: {perception.vision_fps.toFixed(1)} fps</span>
        )}
        <span>Last refresh: {formatTime(result?.refreshedAt)}</span>
        {actionClickPreview && !previewLive && !usingLiveStream && (
          <span className="panel__footer--click-preview">
            {actionClickPreview.previewMode === 'find' ? (
              <>
                Find: {actionClickPreview.matchCount ?? 0} hit
                {actionClickPreview.matchCandidates
                  ? ` (${actionClickPreview.matchCandidates.filter((c) => c.searchMode === 'playspace').length} world · ${actionClickPreview.matchCandidates.filter((c) => c.searchMode === 'inventory').length} inv)`
                  : ''}
              </>
            ) : actionClickPreview.previewMode === 'use_on' &&
              actionClickPreview.fromClientXY &&
              actionClickPreview.toClientXY ? (
              <>
                Use-on: {actionClickPreview.fromClientXY.join(',')} →{' '}
                {actionClickPreview.toClientXY.join(',')}
                {actionClickPreview.slot ? ` · ${actionClickPreview.slot}` : ''}
              </>
            ) : actionClickPreview.clickClientXY ? (
              <>
                Click: {actionClickPreview.clickClientXY.join(',')}
                {actionClickPreview.score != null
                  ? ` · ${actionClickPreview.score.toFixed(2)}`
                  : ''}
                {actionClickPreview.matchCount != null && actionClickPreview.matchCount > 1
                  ? ` · ${actionClickPreview.matchCount} matches (amber = other)`
                  : ''}
              </>
            ) : null}
          </span>
        )}
      </footer>
    </section>
  );
}
