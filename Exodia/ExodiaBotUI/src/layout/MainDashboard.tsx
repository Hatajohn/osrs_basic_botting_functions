import { useRef, type RefObject } from 'react';
import { ActionsPanel } from '../panels/ActionsPanel';
import { BotTasksPanel } from '../panels/BotTasksPanel';
import { LogPanel } from '../panels/LogPanel';
import { TextDebugPanel } from '../panels/TextDebugPanel';
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
  showTextHighlights?: boolean;
  onToggleTextHighlights?: (show: boolean) => void;
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
  /** Shared-stream FSM bot running — keep normal stream preview in RuneLite view. */
  keepStreamPreview?: boolean;
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
  showTextHighlights,
  onToggleTextHighlights,
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
  keepStreamPreview = false,
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
    effectiveLogTextFlex,
    effectiveLogConsoleFlex,
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
    logHidden,
    tasksHidden,
    scriptsHidden,
    actionsHidden,
    rightStripCollapsed,
    rightColumnHidden,
    resizeLog,
    resizeLogText,
    resizeScripts,
    resizeTasks,
    resizeActions,
  } = layoutApi;

  const toggle = (id: PanelId) => () => togglePanelCollapsed(id);

  return (
    <main ref={resolvedContainerRef} className="dashboard">
      {!logHidden && (
        <section
          className={`dashboard__log-column${logCollapsed ? ' dashboard__log-column--strip' : ''}`}
          style={{ flex: effectiveLogFlex }}
        >
          {logCollapsed ? (
            <div className="dashboard__pane dashboard__pane--strip">
              <LogPanel
                entries={logEntries}
                onClear={onClearLog}
                collapsed
                onToggleCollapse={toggle('log')}
              />
            </div>
          ) : (
            <>
              <div className="dashboard__pane" style={{ flex: effectiveLogTextFlex }}>
                <TextDebugPanel
                  streamMeta={streamMeta}
                  streamPortUp={streamPortUp}
                  showTextHighlights={showTextHighlights}
                  onToggleTextHighlights={onToggleTextHighlights}
                />
              </div>
              <Splitter orientation="horizontal" onDrag={resizeLogText} />
              <div className="dashboard__pane" style={{ flex: effectiveLogConsoleFlex }}>
                <LogPanel
                  entries={logEntries}
                  onClear={onClearLog}
                  collapsed={false}
                  onToggleCollapse={toggle('log')}
                />
              </div>
            </>
          )}
        </section>
      )}

      {!logHidden && !logCollapsed && <Splitter orientation="vertical" onDrag={resizeLog} />}

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
            keepStreamPreview={keepStreamPreview}
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
            showTextHighlights={showTextHighlights}
            worldHitCount={worldHitCount}
            overlayAnnotations={overlayAnnotations}
            latestActionPreview={latestActionPreview}
            zoomViewportRef={zoomViewportRef}
            highRes={highRes}
            onToggleHighRes={onToggleHighRes}
          />
        </div>

        {!tasksHidden && !tasksCollapsed && <Splitter orientation="horizontal" onDrag={resizeTasks} />}

        {!tasksHidden && (
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
        )}
      </section>

      {!rightColumnHidden && !rightStripCollapsed && (
        <Splitter orientation="vertical" onDrag={resizeScripts} />
      )}

      {!rightColumnHidden && (
        <section
          className={`dashboard__right${rightStripCollapsed ? ' dashboard__right--strip' : ''}`}
          style={{ flex: effectiveScriptsColumnFlex }}
        >
          {!scriptsHidden && (
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
          )}

          {!scriptsHidden &&
            !actionsHidden &&
            !scriptsCollapsed &&
            !actionsCollapsed &&
            !rightStripCollapsed && <Splitter orientation="horizontal" onDrag={resizeActions} />}

          {!actionsHidden && (
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
          )}
        </section>
      )}
    </main>
  );
}

export { useDashboardLayout, type PanelId };
