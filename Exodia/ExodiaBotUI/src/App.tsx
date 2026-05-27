import { useCallback, useState } from 'react';
import { MenuBar } from './components/MenuBar';
import { useLogStream } from './components/LogConsole';
import { useBotSession } from './hooks/useBotSession';
import { usePerceptionStream } from './hooks/usePerceptionStream';
import { MainDashboard } from './layout/MainDashboard';
import type { MenuActionId, MenuItemDef } from './menu/menuConfig';
import { debugModeForAction } from './menu/menuConfig';
import { SettingsPage } from './pages/SettingsPage';
import type { ActionClickPreview, DebugFrameMode, DebugFrameResult } from '../shared/ipc';
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
    streamRunning,
    streamStale,
    streamImage,
    perception,
    invalidateCache,
    restartStream,
    restarting,
  } = usePerceptionStream();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [aboutDetail, setAboutDetail] = useState('');
  const [debugMode, setDebugMode] = useState<DebugFrameMode>('inventory_identify');
  const [debugResult, setDebugResult] = useState<DebugFrameResult | null>(null);
  const [debugImage, setDebugImage] = useState<string | undefined>();
  const [debugLoading, setDebugLoading] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [actionClickPreview, setActionClickPreview] = useState<ActionClickPreview | null>(null);

  const refreshDebugFrame = useCallback(
    async (mode: DebugFrameMode = debugMode) => {
      if (streamRunning && !(previewLive && botRunning)) {
        await invalidateCache();
        return;
      }
      setDebugLoading(true);
      try {
        const result = await window.exodia.refreshDebugFrame(mode);
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
    [appendLog, debugMode, invalidateCache, previewLive, botRunning, streamRunning],
  );

  const runCalibrateClientRect = useCallback(async () => {
    setCalibrating(true);
    try {
      const result = await window.exodia.runCalibrateClientRect();
      if (result.ok) {
        await window.exodia.startStream();
        if (!streamRunning) {
          await refreshDebugFrame(debugMode);
        }
      }
    } finally {
      setCalibrating(false);
    }
  }, [debugMode, refreshDebugFrame, streamRunning]);

  const prepareActionClickPreview = useCallback(async () => {
    if (previewLive) {
      setPreviewLive(false);
    }
    // Pristine downscaled frame from stream (no inventory overlay) — matches action dry-run coords.
    const frame = await window.exodia.fetchGamePreview();
    if (frame.ok && frame.imageDataUrl) {
      setDebugImage(frame.imageDataUrl);
      setDebugResult({
        ok: true,
        mode: 'raw_client',
        imageDataUrl: frame.imageDataUrl,
        refreshedAt: frame.fetchedAt ?? Date.now(),
      });
      return;
    }
    await refreshDebugFrame('raw_client');
  }, [previewLive, refreshDebugFrame]);

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
          if (!debugImage) {
            appendLog({ line: 'No debug frame to save.', stream: 'system', ts: Date.now() });
            break;
          }
          const saved = await window.exodia.saveDebugSnapshot(debugImage);
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
    [clearLog, appendLog, debugMode, debugImage, refreshDebugFrame, stopBot, pauseBot, resumeBot],
  );

  const displayImage =
    previewLive && botRunning && liveImage
      ? liveImage
      : actionClickPreview && debugImage
        ? debugImage
      : streamRunning && streamImage && !(previewLive && botRunning)
        ? streamImage
        : debugImage;

  return (
    <div className="app">
      <MenuBar
        onAction={handleMenuAction}
        menuContext={{
          botRunning,
          chainDirty: false,
          previewLive: previewLive && botRunning,
          hasDebugFrame: Boolean(displayImage),
          debugMode,
        }}
      />
      <MainDashboard
        logEntries={logEntries}
        onClearLog={clearLog}
        debugResult={debugResult}
        debugImage={displayImage}
        streamRunning={streamRunning}
        streamStale={streamStale}
        streamRestarting={restarting}
        onRestartStream={restartStream}
        perception={perception}
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
        actionClickPreview={actionClickPreview}
        onActionClickPreview={setActionClickPreview}
        onPrepareClickPreview={prepareActionClickPreview}
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
