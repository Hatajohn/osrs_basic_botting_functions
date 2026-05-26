import { useCallback, useEffect, useState } from 'react';
import type { BotRunInfo, RuntimeStatusPayload } from '../../shared/bots';

function isBotActive(run: BotRunInfo | null): boolean {
  if (!run) return false;
  return (
    run.state === 'running' ||
    run.state === 'paused' ||
    run.state === 'starting' ||
    run.state === 'stopping'
  );
}

export function useBotSession() {
  const [botRun, setBotRun] = useState<BotRunInfo | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatusPayload | null>(null);
  const [previewLive, setPreviewLive] = useState(false);
  const [liveImage, setLiveImage] = useState<string | undefined>();

  useEffect(() => {
    window.exodia.getBotRun().then(setBotRun);
    const unsubRun = window.exodia.onBotRunUpdate((run) => {
      setBotRun(run);
      if (run?.usesStream && isBotActive(run)) {
        setPreviewLive(true);
      }
      if (!run) {
        setRuntimeStatus(null);
        setLiveImage(undefined);
        setPreviewLive(false);
      }
    });
    const unsubStatus = window.exodia.onBotStatusUpdate(setRuntimeStatus);
    return () => {
      unsubRun();
      unsubStatus();
    };
  }, []);

  useEffect(() => {
    if (!previewLive || !isBotActive(botRun) || !botRun?.usesStream) {
      return;
    }

    let cancelled = false;
    const poll = async () => {
      const result = await window.exodia.fetchGamePreview();
      if (!cancelled && result.ok && result.imageDataUrl) {
        setLiveImage(result.imageDataUrl);
      }
    };

    poll();
    const id = setInterval(poll, 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [previewLive, botRun]);

  const stopBot = useCallback(async () => {
    await window.exodia.stopBot();
  }, []);

  const pauseBot = useCallback(async () => {
    await window.exodia.sendBotRuntimeCommand('pause');
  }, []);

  const resumeBot = useCallback(async () => {
    await window.exodia.sendBotRuntimeCommand('resume');
  }, []);

  return {
    botRun,
    runtimeStatus,
    botRunning: isBotActive(botRun),
    previewLive,
    setPreviewLive,
    liveImage,
    stopBot,
    pauseBot,
    resumeBot,
  };
}
