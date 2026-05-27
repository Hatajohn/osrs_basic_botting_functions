import { useCallback, useEffect, useRef, useState } from 'react';
import type { PerceptionMeta, StreamStatus } from '../../shared/ipc';

const META_POLL_MS = 1500;
/** ~10 FPS snapshot poll — Electron cannot load localhost MJPEG in <img> reliably. */
const FRAME_POLL_MS = 100;
const FRAME_FAIL_BEFORE_STALE = 8;

export function usePerceptionStream() {
  const [status, setStatus] = useState<StreamStatus | null>(null);
  const [perception, setPerception] = useState<PerceptionMeta | null>(null);
  const [streamImage, setStreamImage] = useState<string | undefined>();
  const [streamStale, setStreamStale] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const frameFailCount = useRef(0);

  const applyStatus = useCallback((next: StreamStatus) => {
    setStatus(next);
    if (next.meta?.perception) {
      setPerception(next.meta.perception);
    }
    if (next.running) {
      setStreamStale(false);
      frameFailCount.current = 0;
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    const next = await window.exodia.getStreamStatus();
    applyStatus(next);
    return next;
  }, [applyStatus]);

  const streamRunning = Boolean(status?.running) && !streamStale;

  useEffect(() => {
    void refreshStatus();
    let attempts = 0;
    const id = setInterval(() => {
      attempts += 1;
      if (attempts > 15) {
        clearInterval(id);
        return;
      }
      void refreshStatus().then((next) => {
        if (next.running) {
          clearInterval(id);
        }
      });
    }, 2000);
    return () => clearInterval(id);
  }, [refreshStatus]);

  useEffect(() => {
    const unsub = window.exodia.onStreamStatusUpdate((next) => {
      applyStatus(next);
    });
    return unsub;
  }, [applyStatus]);

  useEffect(() => {
    if (!streamRunning) {
      setStreamImage(undefined);
      return;
    }

    let cancelled = false;
    let inFlight = false;

    const pollFrame = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        const result = await window.exodia.fetchInventoryOverlay();
        if (cancelled) return;
        if (result.ok && result.imageDataUrl) {
          frameFailCount.current = 0;
          setStreamStale(false);
          setStreamImage(result.imageDataUrl);
        } else {
          frameFailCount.current += 1;
          if (frameFailCount.current >= FRAME_FAIL_BEFORE_STALE) {
            setStreamStale(true);
          }
        }
      } finally {
        inFlight = false;
      }
    };

    pollFrame();
    const id = setInterval(pollFrame, FRAME_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [streamRunning, status?.port]);

  useEffect(() => {
    if (!streamRunning) return;

    let cancelled = false;
    const poll = async () => {
      const result = await window.exodia.fetchStreamMeta();
      if (!cancelled && result.ok && result.meta?.perception) {
        setPerception(result.meta.perception);
      }
    };

    poll();
    const id = setInterval(poll, META_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [streamRunning, status?.port]);

  const invalidateCache = useCallback(async () => {
    await window.exodia.invalidateStreamCache();
  }, []);

  const restartStream = useCallback(async () => {
    setRestarting(true);
    setStreamImage(undefined);
    setStreamStale(false);
    frameFailCount.current = 0;
    try {
      const next = await window.exodia.restartStream();
      applyStatus(next);
      return next;
    } finally {
      setRestarting(false);
    }
  }, [applyStatus]);

  const startStream = useCallback(async () => {
    const next = await window.exodia.startStream();
    applyStatus(next);
    return next;
  }, [applyStatus]);

  return {
    streamRunning,
    streamStale,
    streamAttached: Boolean(status?.attached),
    streamImage,
    streamError: status?.error,
    perception,
    restarting,
    refreshStatus,
    invalidateCache,
    restartStream,
    startStream,
  };
}
