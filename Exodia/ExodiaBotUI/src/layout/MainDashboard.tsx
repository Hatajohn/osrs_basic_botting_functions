import { useRef } from 'react';
import { ActionsPanel } from '../panels/ActionsPanel';
import { BotTasksPanel } from '../panels/BotTasksPanel';
import { LogPanel } from '../panels/LogPanel';
import { RuneLiteViewPanel } from '../panels/RuneLiteViewPanel';
import { ScriptsPanel } from '../panels/ScriptsPanel';
import type { BotRunInfo, RuntimeStatusPayload } from '../../shared/bots';
import type { LogEntry } from '../components/LogConsole';
import type { ActionClickPreview, DebugFrameMode, DebugFrameResult } from '../../shared/ipc';
import { Splitter, useDashboardLayout } from './Splitter';
import './MainDashboard.css';

type MainDashboardProps = {
  logEntries: LogEntry[];
  onClearLog: () => void;
  debugResult?: DebugFrameResult | null;
  debugImage?: string;
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
  actionClickPreview?: ActionClickPreview | null;
  onActionClickPreview?: (preview: ActionClickPreview | null) => void;
  onPrepareClickPreview?: () => Promise<void>;
};

export function MainDashboard({
  logEntries,
  onClearLog,
  debugResult,
  debugImage,
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
  actionClickPreview,
  onActionClickPreview,
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
            imageDataUrl={debugImage}
            result={debugResult}
            loading={debugLoading}
            calibrating={calibrating}
            debugMode={debugMode}
            onRefresh={onRefreshDebugFrame}
            onCalibrate={onCalibrateClientRect}
            previewLive={previewLive}
            onTogglePreviewLive={onTogglePreviewLive}
            botRunning={botRunning}
            actionClickPreview={actionClickPreview}
          />
        </div>

        <Splitter orientation="horizontal" onDrag={resizeTasks} />

        <div className="dashboard__pane" style={{ flex: paneFlex(layout.tasksFlex) }}>
          <BotTasksPanel
            debugResult={debugResult}
            loading={debugLoading}
            botRun={botRun}
            runtimeStatus={runtimeStatus}
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
            onActionClickPreview={onActionClickPreview}
            onPrepareClickPreview={onPrepareClickPreview}
          />
        </div>
      </section>
    </main>
  );
}
