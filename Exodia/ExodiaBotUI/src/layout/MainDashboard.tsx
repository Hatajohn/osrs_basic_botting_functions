import { useRef, type RefObject } from 'react';
import { ActionsPanel } from '../panels/ActionsPanel';
import { BotTasksPanel } from '../panels/BotTasksPanel';
import { LogPanel } from '../panels/LogPanel';
import { RuneLiteViewPanel } from '../panels/RuneLiteViewPanel';
import { ScriptsPanel } from '../panels/ScriptsPanel';
import type { ZoomViewportHandle } from '../components/ZoomableImageViewport';
import type { BotRunInfo, RuntimeStatusPayload } from '../../shared/bots';
import type { LogEntry } from '../components/LogConsole';
import type { ActionClickPreview, DebugFrameMode, DebugFrameResult, StreamMeta } from '../../shared/ipc';
import type { OverlayAnnotationEntry, PushAnnotationOpts, RefreshGroupOpts } from '../hooks/useOverlayAnnotations';
import { Splitter, type PanelId, useDashboardLayout } from './Splitter';
import './MainDashboard.css';

export type DashboardLayoutApi = ReturnType<typeof useDashboardLayout>;

type MainDashboardProps = {
  containerRef?: RefObject<HTMLElement | null>;
  layoutApi: DashboardLayoutApi;
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
  zoomViewportRef?: RefObject<ZoomViewportHandle | null>;
  highRes?: boolean;
  onToggleHighRes?: (enabled: boolean) => void;
};

export function MainDashboard({
  containerRef,
  layoutApi,
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
  zoomViewportRef,
  highRes,
  onToggleHighRes,
}: MainDashboardProps) {
  const internalContainerRef = useRef<HTMLElement>(null);
  const resolvedContainerRef = containerRef ?? internalContainerRef;

  const {
    togglePanelCollapsed,
    effectiveLogFlex,
    effectiveCenterFlex,
    effectiveScriptsColumnFlex,
    effectiveRuneliteFlex,
    effectiveTasksFlex,
    effectiveScriptsFlex,
    effectiveActionsFlex,
    logCollapsed,
    tasksCollapsed,
    scriptsCollapsed,
    actionsCollapsed,
    rightStripCollapsed,
    resizeLog,
    resizeScripts,
    resizeTasks,
    resizeActions,
  } = layoutApi;

  const toggle = (id: PanelId) => () => togglePanelCollapsed(id);

  return (
    <main ref={resolvedContainerRef} className="dashboard">
      <section
        className={`dashboard__pane${logCollapsed ? ' dashboard__pane--strip' : ''}`}
        style={{ flex: effectiveLogFlex }}
      >
        <LogPanel
          entries={logEntries}
          onClear={onClearLog}
          collapsed={logCollapsed}
          onToggleCollapse={toggle('log')}
        />
      </section>

      {!logCollapsed && <Splitter orientation="vertical" onDrag={resizeLog} />}

      <section className="dashboard__center" style={{ flex: effectiveCenterFlex }}>
        <div className="dashboard__pane" style={{ flex: effectiveRuneliteFlex }}>
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
            zoomViewportRef={zoomViewportRef}
            highRes={highRes}
            onToggleHighRes={onToggleHighRes}
          />
        </div>

        {!tasksCollapsed && <Splitter orientation="horizontal" onDrag={resizeTasks} />}

        <div
          className={`dashboard__pane${tasksCollapsed ? ' dashboard__pane--header-only' : ''}`}
          style={{ flex: effectiveTasksFlex }}
        >
          <BotTasksPanel
            debugResult={debugResult}
            loading={debugLoading}
            botRun={botRun}
            runtimeStatus={runtimeStatus}
            streamRunning={streamRunning}
            collapsed={tasksCollapsed}
            onToggleCollapse={toggle('tasks')}
          />
        </div>
      </section>

      {!rightStripCollapsed && <Splitter orientation="vertical" onDrag={resizeScripts} />}

      <section
        className={`dashboard__right${rightStripCollapsed ? ' dashboard__right--strip' : ''}`}
        style={{ flex: effectiveScriptsColumnFlex }}
      >
        <div
          className={`dashboard__pane${scriptsCollapsed || rightStripCollapsed ? ' dashboard__pane--header-only' : ''}${rightStripCollapsed ? ' dashboard__pane--strip-slot' : ''}`}
          style={{ flex: effectiveScriptsFlex }}
        >
          <ScriptsPanel
            collapsed={scriptsCollapsed}
            onToggleCollapse={toggle('scripts')}
            stripMode={rightStripCollapsed}
          />
        </div>

        {!scriptsCollapsed && !actionsCollapsed && !rightStripCollapsed && (
          <Splitter orientation="horizontal" onDrag={resizeActions} />
        )}

        <div
          className={`dashboard__pane${actionsCollapsed || rightStripCollapsed ? ' dashboard__pane--header-only' : ''}${rightStripCollapsed ? ' dashboard__pane--strip-slot' : ''}`}
          style={{ flex: effectiveActionsFlex }}
        >
          <ActionsPanel
            botRunning={botRunning}
            latestActionPreview={latestActionPreview}
            onPushOverlayAnnotation={onPushOverlayAnnotation}
            onClearOverlayGroup={onClearOverlayGroup}
            onPrepareClickPreview={onPrepareClickPreview}
            collapsed={actionsCollapsed}
            onToggleCollapse={toggle('actions')}
            stripMode={rightStripCollapsed}
          />
        </div>
      </section>
    </main>
  );
}

export { useDashboardLayout, type PanelId };
