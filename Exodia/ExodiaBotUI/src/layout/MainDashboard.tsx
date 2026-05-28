import { useRef } from 'react';
import { ActionsPanel } from '../panels/ActionsPanel';
import { BotTasksPanel } from '../panels/BotTasksPanel';
import { LogPanel } from '../panels/LogPanel';
import { RuneLiteViewPanel } from '../panels/RuneLiteViewPanel';
import { ScriptsPanel } from '../panels/ScriptsPanel';
import type { BotRunInfo, RuntimeStatusPayload } from '../../shared/bots';
import type { LogEntry } from '../components/LogConsole';
import type { ActionClickPreview, DebugFrameMode, DebugFrameResult, StreamMeta } from '../../shared/ipc';
import type { OverlayAnnotationEntry, PushAnnotationOpts, RefreshGroupOpts } from '../hooks/useOverlayAnnotations';
import { Splitter, useDashboardLayout } from './Splitter';
import './MainDashboard.css';

type MainDashboardProps = {
  logEntries: LogEntry[];
  onClearLog: () => void;
  debugResult?: DebugFrameResult | null;
  viewportImage?: string;
  streamPortUp?: boolean;
  streamRunning?: boolean;
  streamStale?: boolean;
  streamRestarting?: boolean;
  streamError?: string;
  onRestartStream?: () => Promise<unknown>;
  perception?: import('../../shared/ipc').InventoryPerceptionMeta | null;
  streamMeta?: StreamMeta | null;
  showStreamDebugOverlay?: boolean;
  onToggleStreamDebugOverlay?: (show: boolean) => void;
  showTemplateTracks?: boolean;
  showInventoryTracks?: boolean;
  worldHitCount?: number;
  debugLoading: boolean;
  calibrating: boolean;
  debugMode: DebugFrameMode;
  onRefreshDebugFrame: () => void;
  onCalibrateClientRect: () => void;
  botRun?: BotRunInfo | null;
  runtimeStatus?: RuntimeStatusPayload | null;
  previewLive?: boolean;
  onTogglePreviewLive?: (live: boolean) => void;
  botRunning?: boolean;
  overlayAnnotations?: OverlayAnnotationEntry[];
  latestActionPreview?: ActionClickPreview | null;
  onPushOverlayAnnotation?: (preview: ActionClickPreview, opts?: PushAnnotationOpts) => string;
  onClearOverlayGroup?: (blockId: string) => void;
  onRefreshOverlayGroup?: (blockId: string, opts?: RefreshGroupOpts) => void;
  onPrepareClickPreview?: () => Promise<void>;
};

export function MainDashboard({
  logEntries,
  onClearLog,
  debugResult,
  viewportImage,
  streamPortUp,
  streamRunning,
  streamStale,
  streamRestarting,
  streamError,
  onRestartStream,
  perception,
  streamMeta,
  showStreamDebugOverlay,
  onToggleStreamDebugOverlay,
  showTemplateTracks,
  showInventoryTracks,
  worldHitCount,
  debugLoading,
  calibrating,
  debugMode,
  onRefreshDebugFrame,
  onCalibrateClientRect,
  botRun,
  runtimeStatus,
  previewLive,
  onTogglePreviewLive,
  botRunning,
  overlayAnnotations = [],
  latestActionPreview = null,
  onPushOverlayAnnotation,
  onClearOverlayGroup,
  onRefreshOverlayGroup,
  onPrepareClickPreview,
}: MainDashboardProps) {
  const containerRef = useRef<HTMLElement>(null);
  const {
    layout,
    centerPct,
    runeliteFlex,
    scriptsColumnFlex,
    paneFlex,
    resizeLog,
    resizeScripts,
    resizeTasks,
    resizeActions,
  } = useDashboardLayout(containerRef);

  return (
    <main ref={containerRef} className="dashboard">
      <section className="dashboard__pane" style={{ flex: paneFlex(layout.logPct) }}>
        <LogPanel entries={logEntries} onClear={onClearLog} />
      </section>

      <Splitter orientation="vertical" onDrag={resizeLog} />

      <section className="dashboard__center" style={{ flex: paneFlex(centerPct) }}>
        <div className="dashboard__pane" style={{ flex: paneFlex(runeliteFlex) }}>
          <RuneLiteViewPanel
            viewportImage={viewportImage}
            result={debugResult}
            loading={debugLoading}
            calibrating={calibrating}
            debugMode={debugMode}
            onRefresh={onRefreshDebugFrame}
            onCalibrate={onCalibrateClientRect}
            previewLive={previewLive}
            onTogglePreviewLive={onTogglePreviewLive}
            botRunning={botRunning}
            streamPortUp={streamPortUp}
            streamRunning={streamRunning}
            streamStale={streamStale}
            streamRestarting={streamRestarting}
            streamError={streamError}
            onRestartStream={onRestartStream}
            perception={perception}
            streamMeta={streamMeta}
            showStreamDebugOverlay={showStreamDebugOverlay}
            onToggleStreamDebugOverlay={onToggleStreamDebugOverlay}
            showTemplateTracks={showTemplateTracks}
            showInventoryTracks={showInventoryTracks}
            worldHitCount={worldHitCount}
            overlayAnnotations={overlayAnnotations}
            latestActionPreview={latestActionPreview}
          />
        </div>

        <Splitter orientation="horizontal" onDrag={resizeTasks} />

        <div className="dashboard__pane" style={{ flex: paneFlex(layout.tasksFlex) }}>
          <BotTasksPanel
            debugResult={debugResult}
            loading={debugLoading}
            botRun={botRun}
            runtimeStatus={runtimeStatus}
            streamRunning={streamRunning}
          />
        </div>
      </section>

      <Splitter orientation="vertical" onDrag={resizeScripts} />

      <section className="dashboard__right" style={{ flex: paneFlex(layout.scriptsPct) }}>
        <div className="dashboard__pane" style={{ flex: paneFlex(scriptsColumnFlex) }}>
          <ScriptsPanel />
        </div>

        <Splitter orientation="horizontal" onDrag={resizeActions} />

        <div className="dashboard__pane" style={{ flex: paneFlex(layout.actionsFlex) }}>
          <ActionsPanel
            botRunning={botRunning}
            latestActionPreview={latestActionPreview}
            onPushOverlayAnnotation={onPushOverlayAnnotation}
            onClearOverlayGroup={onClearOverlayGroup}
            onPrepareClickPreview={onPrepareClickPreview}
          />
        </div>
      </section>
    </main>
  );
}
