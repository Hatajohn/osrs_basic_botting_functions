import { useCallback, useEffect, useRef, useState } from 'react';
import { MenuBar } from './components/MenuBar';
import { useLogStream } from './components/LogConsole';
import type { ZoomViewportHandle } from './components/ZoomableImageViewport';
import { useBotSession } from './hooks/useBotSession';
import { useOverlayAnnotations } from './hooks/useOverlayAnnotations';
import { usePerceptionStream } from './hooks/usePerceptionStream';
import { MainDashboard, useDashboardLayout } from './layout/MainDashboard';
import type { MenuActionId, MenuItemDef } from './menu/menuConfig';
import { debugModeForAction } from './menu/menuConfig';
import { SettingsPage } from './pages/SettingsPage';
import type { DebugFrameMode, DebugFrameResult } from '../shared/ipc';
import './App.css';

function AboutModal({
  open,
  onClose,
  detail,
}: {
  open: boolean;
  onClose: () => void;
  detail: string;
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <dialog className="about-modal" open onClick={(e) => e.stopPropagation()}>
        <h2>About Exodia</h2>
        <pre className="about-modal__detail">{detail}</pre>
        <footer>
          <button type="button" className="btn btn--primary" onClick={onClose}>
            OK
          </button>
        </footer>
      </dialog>
    </div>
  );
}

export default function App() {
  const [logEntries, clearLog, appendLog] = useLogStream();
  const {
    botRun,
    runtimeStatus,
    botRunning,
    previewLive,
    setPreviewLive,
    liveImage,
    stopBot,
    pauseBot,
    resumeBot,
  } = useBotSession();
  const {
    streamPortUp,
    streamRunning,
    streamStale,
    streamImage,
    streamMeta,
    perception,
    worldHitCount,
    invalidateCache,
    restartStream,
    startStream,
    restarting,
    streamError,
  } = usePerceptionStream();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [aboutDetail, setAboutDetail] = useState('');
  const [showStreamDebugOverlay, setShowStreamDebugOverlay] = useState(false);
  const [debugMode, setDebugMode] = useState<DebugFrameMode>('inventory_identify');
  const [debugResult, setDebugResult] = useState<DebugFrameResult | null>(null);
  const [debugImage, setDebugImage] = useState<string | undefined>();
  const [debugLoading, setDebugLoading] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [highRes, setHighRes] = useState(false);
  const zoomViewportRef = useRef<ZoomViewportHandle>(null);
  const dashboardRef = useRef<HTMLElement>(null);
  const dashboardLayout = useDashboardLayout(dashboardRef);
  const {
    annotations: overlayAnnotations,
    latestPreview: latestActionPreview,
    pushAnnotation,
    clearGroup: clearOverlayGroup,
    refreshGroup: refreshOverlayGroup,
  } = useOverlayAnnotations();

  useEffect(() => {
    void window.exodia.getSettings().then(({ settings }) => {
      setHighRes((settings.streamMaxWidth ?? 640) === 0);
    });
  }, []);

  const applyHighRes = useCallback(
    async (enabled: boolean) => {
      const maxWidth = enabled ? 0 : 640;
      setHighRes(enabled);
      await window.exodia.setSettings({ streamMaxWidth: maxWidth });
      if (streamRunning) {
        await restartStream();
      }
    },
    [restartStream, streamRunning],
  );

  const refreshDebugFrame = useCallback(
    async (mode: DebugFrameMode = debugMode) => {
      if (streamRunning && !(previewLive && botRunning)) {
        await invalidateCache();
        return;
      }
      setDebugLoading(true);
      try {
        const result = await window.exodia.refreshDebugFrame(mode, {
          maxWidth: highRes ? 0 : 640,
        });
        setDebugResult(result);
        if (result.ok && result.imageDataUrl) {
          setDebugImage(result.imageDataUrl);
        }
        if (!result.ok) {
          appendLog({
            line: result.hint ? `${result.error} — ${result.hint}` : (result.error ?? 'Debug refresh failed'),
            stream: 'stderr',
            ts: Date.now(),
          });
        }
      } finally {
        setDebugLoading(false);
      }
    },
    [appendLog, debugMode, highRes, invalidateCache, previewLive, botRunning, streamRunning],
  );

  const runCalibrateClientRect = useCallback(async () => {
    setCalibrating(true);
    try {
      await window.exodia.runCalibrateClientRect();
      // Main process stops capture, runs calibration, then hard-restarts stream.
    } finally {
      setCalibrating(false);
    }
  }, []);

  const prepareActionClickPreview = useCallback(async () => {
    if (previewLive) {
      setPreviewLive(false);
    }
    // Stream stays the base layer; action overlays stack on top (no debug-image swap).
  }, [previewLive, setPreviewLive]);

  const keepStreamPreview = Boolean(botRun?.usesSharedStream && botRunning);

  const viewportImage =
    previewLive && botRunning && liveImage && !keepStreamPreview
      ? liveImage
      : streamPortUp && streamImage && (!previewLive || keepStreamPreview)
        ? streamImage
        : debugImage;

  const handleMenuAction = useCallback(
    async (actionId: MenuActionId, _item: MenuItemDef) => {
      switch (actionId) {
        case 'clearLog':
          clearLog();
          break;
        case 'preferences':
          setSettingsOpen(true);
          break;
        case 'quit':
          await window.exodia.quit();
          break;
        case 'about': {
          const { resolved, settings } = await window.exodia.getSettings();
          setAboutDetail(
            [
              'Exodia Desktop v0.2.0 (Phase 2)',
              '',
              `Exodia root: ${resolved.exodiaRoot}`,
              `Python: ${resolved.pythonPath}`,
              `Logs: ${resolved.logsDir}`,
              `Stream port: ${settings.streamPort}`,
            ].join('\n'),
          );
          setAboutOpen(true);
          break;
        }
        case 'refreshDebugFrame':
          await refreshDebugFrame(debugMode);
          break;
        case 'saveSnapshot': {
          const snapshot = viewportImage;
          if (!snapshot) {
            appendLog({ line: 'No frame to save.', stream: 'system', ts: Date.now() });
            break;
          }
          const saved = await window.exodia.saveDebugSnapshot(snapshot);
          if (saved.ok && saved.path) {
            appendLog({ line: `Saved snapshot: ${saved.path}`, stream: 'system', ts: Date.now() });
          } else if (!saved.canceled && saved.error) {
            appendLog({ line: saved.error, stream: 'stderr', ts: Date.now() });
          }
          break;
        }
        case 'debugModeInventoryIdentify':
        case 'debugModeRawClient':
        case 'debugModeGrid': {
          const mode = debugModeForAction(actionId);
          if (mode) setDebugMode(mode);
          break;
        }
        case 'zoomIn':
          zoomViewportRef.current?.zoomIn();
          break;
        case 'zoomOut':
          zoomViewportRef.current?.zoomOut();
          break;
        case 'zoomFit':
          zoomViewportRef.current?.zoomFit();
          break;
        case 'toggleHighRes':
          await applyHighRes(!highRes);
          break;
        case 'toggleLogPanel':
          dashboardLayout.togglePanelHidden('log');
          break;
        case 'toggleTasksPanel':
          dashboardLayout.togglePanelHidden('tasks');
          break;
        case 'toggleScriptsPanel':
          dashboardLayout.togglePanelHidden('scripts');
          break;
        case 'toggleActionsPanel':
          dashboardLayout.togglePanelHidden('actions');
          break;
        case 'toggleClientOnly':
          dashboardLayout.toggleClientOnly();
          break;
        case 'botStop':
          await stopBot();
          break;
        case 'botPause':
          await pauseBot();
          break;
        case 'botResume':
          await resumeBot();
          break;
        case 'openLogsFolder':
          await window.exodia.openLogsFolder();
          break;
        default:
          appendLog({
            line: 'Not available yet.',
            stream: 'system',
            ts: Date.now(),
          });
      }
    },
    [clearLog, appendLog, applyHighRes, dashboardLayout, debugMode, highRes, refreshDebugFrame, stopBot, pauseBot, resumeBot, viewportImage],
  );

  return (
    <div className="app">
      <MenuBar
        onAction={handleMenuAction}
        onZoomIn={() => zoomViewportRef.current?.zoomIn()}
        onZoomOut={() => zoomViewportRef.current?.zoomOut()}
        onZoomFit={() => zoomViewportRef.current?.zoomFit()}
        menuContext={{
          botRunning,
          chainDirty: false,
          previewLive: previewLive && botRunning,
          hasDebugFrame: Boolean(viewportImage),
          streamRunning,
          debugMode,
          hasZoomViewport: Boolean(viewportImage),
          highRes,
          panelsVisible: {
            log: !dashboardLayout.logHidden,
            tasks: !dashboardLayout.tasksHidden,
            scripts: !dashboardLayout.scriptsHidden,
            actions: !dashboardLayout.actionsHidden,
            clientOnly:
              dashboardLayout.logHidden &&
              dashboardLayout.tasksHidden &&
              dashboardLayout.scriptsHidden &&
              dashboardLayout.actionsHidden,
          },
        }}
      />
      <MainDashboard
        containerRef={dashboardRef}
        layoutApi={dashboardLayout}
        logEntries={logEntries}
        onClearLog={clearLog}
        debugResult={debugResult}
        viewportImage={viewportImage}
        streamPortUp={streamPortUp}
        streamRunning={streamRunning}
        streamStale={streamStale}
        streamRestarting={restarting}
        streamError={streamError}
        onRestartStream={restartStream}
        perception={perception}
        streamMeta={streamMeta}
        showStreamDebugOverlay={showStreamDebugOverlay}
        onToggleStreamDebugOverlay={setShowStreamDebugOverlay}
        worldHitCount={worldHitCount}
        debugLoading={debugLoading}
        calibrating={calibrating}
        debugMode={debugMode}
        onRefreshDebugFrame={() => refreshDebugFrame(debugMode)}
        onCalibrateClientRect={runCalibrateClientRect}
        botRun={botRun}
        runtimeStatus={runtimeStatus}
        previewLive={previewLive}
        onTogglePreviewLive={setPreviewLive}
        botRunning={botRunning}
        keepStreamPreview={keepStreamPreview}
        overlayAnnotations={overlayAnnotations}
        latestActionPreview={latestActionPreview}
        onPushOverlayAnnotation={pushAnnotation}
        onClearOverlayGroup={clearOverlayGroup}
        onRefreshOverlayGroup={refreshOverlayGroup}
        onPrepareClickPreview={prepareActionClickPreview}
        zoomViewportRef={zoomViewportRef}
        highRes={highRes}
        onToggleHighRes={(enabled) => void applyHighRes(enabled)}
      />
      <SettingsPage
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onCalibrate={runCalibrateClientRect}
        calibrating={calibrating}
      />
      <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} detail={aboutDetail} />
    </div>
  );
}
