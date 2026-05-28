import { useRef, useState, type RefObject } from 'react';
import { EphemeralOverlayLayer } from '../components/EphemeralOverlayLayer';
import { PerceptionDebugOverlay } from '../components/PerceptionDebugOverlay';
import {
  ZoomableImageViewport,
  zoomPercent,
  type ZoomViewportHandle,
  type ZoomViewportInfo,
} from '../components/ZoomableImageViewport';
import { TemplateWatchPanel } from './TemplateWatchPanel';
import type { OverlayAnnotationEntry } from '../hooks/useOverlayAnnotations';
import type {
  ActionClickPreview,
  DebugFrameMode,
  DebugFrameResult,
  InventoryPerceptionMeta,
  StreamMeta,
} from '../../shared/ipc';
import './Panel.css';

type RuneLiteViewPanelProps = {
  viewportImage?: string;
  result?: DebugFrameResult | null;
  loading: boolean;
  calibrating: boolean;
  debugMode: DebugFrameMode;
  onRefresh: () => void;
  onCalibrate: () => void;
  previewLive?: boolean;
  onTogglePreviewLive?: (live: boolean) => void;
  botRunning?: boolean;
  streamPortUp?: boolean;
  streamRunning?: boolean;
  streamStale?: boolean;
  streamRestarting?: boolean;
  streamError?: string;
  onRestartStream?: () => Promise<unknown>;
  perception?: InventoryPerceptionMeta | null;
  streamMeta?: StreamMeta | null;
  showStreamDebugOverlay?: boolean;
  showTemplateTracks?: boolean;
  showInventoryTracks?: boolean;
  onToggleStreamDebugOverlay?: (show: boolean) => void;
  worldHitCount?: number;
  overlayAnnotations?: OverlayAnnotationEntry[];
  latestActionPreview?: ActionClickPreview | null;
  zoomViewportRef?: RefObject<ZoomViewportHandle | null>;
  highRes?: boolean;
  onToggleHighRes?: (enabled: boolean) => void;
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

function formatDimensions(info: ZoomViewportInfo | null, result?: DebugFrameResult | null, meta?: StreamMeta | null): string | null {
  if (info && info.naturalWidth > 0 && info.naturalHeight > 0) {
    return `${info.naturalWidth}×${info.naturalHeight}`;
  }
  if (result?.sourceWidth && result?.sourceHeight) {
    return `${result.sourceWidth}×${result.sourceHeight}`;
  }
  if (result?.width && result?.height) {
    return `${result.width}×${result.height}`;
  }
  if (meta?.frame_width && meta?.frame_height) {
    return `${meta.frame_width}×${meta.frame_height}`;
  }
  return null;
}

export function RuneLiteViewPanel({
  viewportImage,
  result,
  loading,
  calibrating,
  debugMode,
  onRefresh,
  onCalibrate,
  previewLive = false,
  onTogglePreviewLive,
  botRunning = false,
  streamPortUp = false,
  streamRunning = false,
  streamStale = false,
  streamRestarting = false,
  streamError,
  onRestartStream,
  perception = null,
  streamMeta = null,
  showStreamDebugOverlay = false,
  showTemplateTracks = true,
  showInventoryTracks = true,
  onToggleStreamDebugOverlay,
  worldHitCount,
  overlayAnnotations = [],
  latestActionPreview = null,
  zoomViewportRef,
  highRes = false,
  onToggleHighRes,
}: RuneLiteViewPanelProps) {
  const imageRef = useRef<HTMLImageElement>(null);
  const [watchCollapsed, setWatchCollapsed] = useState(false);
  const [zoomInfo, setZoomInfo] = useState<ZoomViewportInfo | null>(null);
  const showingStreamBase = Boolean(streamPortUp && viewportImage && !previewLive && !botRunning);
  const usingLiveStream = Boolean(streamRunning && !previewLive && !botRunning);
  const showStreamControls = Boolean(!previewLive && !botRunning && onRestartStream);
  const streamRecovery = !streamPortUp && !previewLive && !botRunning;
  const hasImage = Boolean(viewportImage);
  const error = result && !result.ok ? result.error : undefined;
  const hint = result && !result.ok ? result.hint : undefined;
  const busy = loading || calibrating;
  const templateStats = streamMeta?.perception?.world?.template_stats ?? [];
  const invTemplateStats = streamMeta?.perception?.inventory?.inventory_template_stats ?? [];
  const modeLabel = previewLive && botRunning
    ? 'Live preview'
    : streamStale && showingStreamBase
      ? 'Stream stale'
      : usingLiveStream
        ? 'Live stream'
        : formatMode(debugMode);
  const zoomResetKey = showingStreamBase || (previewLive && botRunning) ? undefined : result?.refreshedAt;
  const dimensionsLabel = formatDimensions(zoomInfo, result ?? undefined, streamMeta ?? undefined);
  const zoomLabel =
    zoomInfo && zoomInfo.fitScale > 0
      ? `${zoomPercent(zoomInfo.scale, zoomInfo.fitScale)}%`
      : null;

  return (
    <section className="panel panel--runelite">
      <header className="panel__header">
        <h2 className="panel__title">RuneLite view</h2>
        <div className="panel__header-actions">
          <span
            className={`panel__badge${
              previewLive && botRunning
                ? ' panel__badge--live'
                : usingLiveStream
                  ? ' panel__badge--live'
                  : streamStale && showingStreamBase
                    ? ' panel__badge--warn'
                    : ''
            }`}
          >
            {previewLive && botRunning
              ? 'Live'
              : usingLiveStream
                ? 'Stream'
                : streamStale
                  ? 'Stream stale'
                  : 'Debug'}
          </span>
          {hasImage && (
            <div className="panel__zoom-toolbar" title="Ctrl+wheel to zoom · Space or middle-click to pan">
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => zoomViewportRef?.current?.zoomOut()}
                title="Zoom out (Ctrl+-)"
              >
                −
              </button>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => zoomViewportRef?.current?.zoom100()}
                title="100% pixel size"
              >
                100%
              </button>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => zoomViewportRef?.current?.zoomIn()}
                title="Zoom in (Ctrl+=)"
              >
                +
              </button>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => zoomViewportRef?.current?.zoomFit()}
                title="Fit to panel (Ctrl+0)"
              >
                Fit
              </button>
            </div>
          )}
          {onToggleHighRes && (
            <label className="panel__high-res-toggle" title="Full client resolution (restarts stream when live)">
              <input
                type="checkbox"
                checked={highRes}
                onChange={(e) => onToggleHighRes(e.target.checked)}
                disabled={busy || streamRestarting}
              />
              High res
            </label>
          )}
          {showStreamControls && onToggleStreamDebugOverlay && (
            <button
              type="button"
              className={`btn btn--sm${showStreamDebugOverlay ? ' btn--active' : ''}`}
              onClick={() => onToggleStreamDebugOverlay(!showStreamDebugOverlay)}
              title="IDs view: numbered inventory slots with an ID list from /meta"
            >
              {showStreamDebugOverlay ? 'Hide IDs' : 'IDs view'}
            </button>
          )}
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
            title={
              usingLiveStream
                ? 'Force full re-identify on next stream frame'
                : streamStale && showingStreamBase
                  ? 'Stream capture_seq frozen — try Hard reset stream'
                  : streamRecovery
                    ? 'Recovery: capture a one-off debug frame when the perception stream is offline'
                    : undefined
            }
          >
            {loading
              ? showingStreamBase
                ? 'Re-analyzing…'
                : 'Capturing…'
              : showingStreamBase
                ? 'Re-analyze'
                : streamRecovery
                  ? 'Debug capture'
                  : 'Refresh'}
          </button>
        </div>
      </header>
      <div className="panel--runelite-stack">
        <div className="panel__body panel__runelite-body">
        {loading && !hasImage && (
          <div className="panel__placeholder">
            <p>
              {showingStreamBase || streamPortUp
                ? 'Waiting for perception stream frames…'
                : 'Capturing client and running inventory detect…'}
            </p>
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
                    ? 'Stream stopped responding — use Hard reset stream below.'
                    : streamRunning
                      ? 'Waiting for perception stream frames…'
                      : 'Calibrate the RuneLite client window to start the live perception stream.'}
            </p>
            {!previewLive && !streamRunning && !streamStale && (
              <>
                <p className="panel__hint">
                  {streamError
                    ? streamError
                    : 'Requires client_rect.json and a visible RuneLite window.'}
                </p>
                <div className="panel__placeholder-actions">
                  <button type="button" className="btn btn--sm btn--primary" onClick={onCalibrate} disabled={busy}>
                    {calibrating ? 'Calibrating…' : 'Calibrate'}
                  </button>
                  {onRestartStream && (
                    <button
                      type="button"
                      className="btn btn--sm"
                      onClick={() => void onRestartStream()}
                      disabled={busy || streamRestarting}
                    >
                      {streamRestarting ? 'Resetting…' : 'Hard reset stream'}
                    </button>
                  )}
                </div>
              </>
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
        {hasImage && viewportImage && (
          <ZoomableImageViewport
            ref={zoomViewportRef}
            baseSrc={viewportImage}
            imageRef={imageRef}
            resetKey={zoomResetKey}
            onZoomChange={setZoomInfo}
            alt={
              previewLive && botRunning
                ? 'RuneLite live preview'
                : showingStreamBase
                  ? streamStale
                    ? 'RuneLite stream (stale)'
                    : 'RuneLite live stream'
                  : 'RuneLite debug frame'
            }
          >
            {showingStreamBase &&
              (showStreamDebugOverlay || showTemplateTracks || showInventoryTracks) && (
              <PerceptionDebugOverlay
                meta={streamMeta}
                showInventoryDebug={showStreamDebugOverlay}
                showInventoryTracks={showInventoryTracks}
                showWorldTracks={showTemplateTracks}
              />
            )}
            <EphemeralOverlayLayer annotations={overlayAnnotations} />
          </ZoomableImageViewport>
        )}
        </div>
        {showingStreamBase && (
          <TemplateWatchPanel
            streamMeta={streamMeta}
            collapsed={watchCollapsed}
            onToggleCollapsed={() => setWatchCollapsed((v) => !v)}
          />
        )}
      </div>
      <footer className="panel__footer panel__footer--stats">
        <span>Mode: {modeLabel}</span>
        {zoomLabel && <span>Zoom: {zoomLabel}</span>}
        {dimensionsLabel && <span>{dimensionsLabel}</span>}
        {showingStreamBase && streamMeta?.capture_seq != null && (
          <span>seq: {streamMeta.capture_seq}</span>
        )}
        {showingStreamBase && perception?.occupied != null && (
          <span>Occupied: {perception.occupied}</span>
        )}
        {showingStreamBase && perception?.unknown != null && <span>?: {perception.unknown}</span>}
        {showingStreamBase && perception?.tmp_count != null && (
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
        {showingStreamBase && perception?.vision_fps != null && (
          <span>Vision: {perception.vision_fps.toFixed(1)} fps</span>
        )}
        {showingStreamBase && worldHitCount != null && (
          <span>World hits: {worldHitCount}</span>
        )}
        {showingStreamBase && templateStats.length > 0 && (
          <span
            className="panel__footer--tracks"
            title={templateStats
              .map((s) => `${s.template}: ${s.hits} hit(s)${s.best_score != null ? ` · ${s.best_score.toFixed(2)}` : ''}`)
              .join('\n')}
          >
            World tracks:{' '}
            {templateStats.map((s) => `${s.template}:${s.hits}`).join(' · ')}
          </span>
        )}
        {showingStreamBase && invTemplateStats.length > 0 && (
          <span
            className="panel__footer--tracks"
            title={invTemplateStats
              .map((s) => {
                const src = s.source ? ` · ${s.source}` : '';
                const score = s.best_score != null ? ` · ${s.best_score.toFixed(2)}` : '';
                return `${s.template}: ${s.slots} slot(s)${score}${src}`;
              })
              .join('\n')}
          >
            Inv tracks:{' '}
            {invTemplateStats.map((s) => `${s.template}:${s.slots}`).join(' · ')}
          </span>
        )}
        <span>Last refresh: {formatTime(result?.refreshedAt)}</span>
        {latestActionPreview && (
          <span className="panel__footer--click-preview">
            {latestActionPreview.previewMode === 'find' ? (
              <>
                Find: {latestActionPreview.matchCount ?? 0} hit
                {latestActionPreview.matchCandidates
                  ? ` (${latestActionPreview.matchCandidates.filter((c) => c.searchMode === 'playspace').length} world · ${latestActionPreview.matchCandidates.filter((c) => c.searchMode === 'inventory').length} inv)`
                  : ''}
              </>
            ) : latestActionPreview.previewMode === 'use_on' &&
              latestActionPreview.fromClientXY &&
              latestActionPreview.toClientXY ? (
              <>
                Use-on: {latestActionPreview.fromClientXY.join(',')} →{' '}
                {latestActionPreview.toClientXY.join(',')}
                {latestActionPreview.slot ? ` · ${latestActionPreview.slot}` : ''}
              </>
            ) : latestActionPreview.clickClientXY ? (
              <>
                Click: {latestActionPreview.clickClientXY.join(',')}
                {latestActionPreview.score != null
                  ? ` · ${latestActionPreview.score.toFixed(2)}`
                  : ''}
                {latestActionPreview.matchCount != null && latestActionPreview.matchCount > 1
                  ? ` · ${latestActionPreview.matchCount} matches (amber = other)`
                  : ''}
              </>
            ) : null}
          </span>
        )}
      </footer>
    </section>
  );
}
