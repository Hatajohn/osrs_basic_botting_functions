import { useCallback, useEffect, useRef, useState } from 'react';
import type { InventoryPerceptionMeta, StreamMeta, StreamStatus } from '../../shared/ipc';

/** Poll /meta often enough to observe capture_seq (~verifyStreamHealthy gap). */
const META_POLL_MS = 500;
/** ~10 FPS snapshot poll — pristine game_preview (no baked server overlays). */
const FRAME_POLL_MS = 100;
const FRAME_FAIL_BEFORE_STALE = 8;
/** Mark stream stale when capture_seq is unchanged this long (cached JPEG may still poll). */
const FROZEN_SEQ_STALE_MS = 3000;
/** How often to re-check frozen capture_seq between meta polls. */
const FROZEN_SEQ_CHECK_MS = 500;

export function usePerceptionStream() {
  const [status, setStatus] = useState<StreamStatus | null>(null);
  const [perception, setPerception] = useState<InventoryPerceptionMeta | null>(null);
  const [streamMeta, setStreamMeta] = useState<StreamMeta | null>(null);
  const [worldHitCount, setWorldHitCount] = useState<number | undefined>();
  const [streamImage, setStreamImage] = useState<string | undefined>();
  const [streamStale, setStreamStale] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const frameFailCount = useRef(0);
  const lastCaptureSeq = useRef<number | undefined>(undefined);
  const lastCaptureSeqChangeMs = useRef<number>(Date.now());

  const noteCaptureSeq = useCallback((seq: number) => {
    if (lastCaptureSeq.current !== seq) {
      lastCaptureSeq.current = seq;
      lastCaptureSeqChangeMs.current = Date.now();
      setStreamStale(false);
      return;
    }
    if (Date.now() - lastCaptureSeqChangeMs.current >= FROZEN_SEQ_STALE_MS) {
      setStreamStale(true);
    }
  }, []);

  const applyStreamMeta = useCallback((meta: StreamMeta | null | undefined) => {
    if (!meta) return;
    setStreamMeta(meta);
    if (meta.capture_seq != null) {
      noteCaptureSeq(meta.capture_seq);
    }
    if (meta.perception?.inventory) {
      setPerception(meta.perception.inventory);
    }
    if (meta.perception?.world?.hit_count != null) {
      setWorldHitCount(meta.perception.world.hit_count);
    }
  }, [noteCaptureSeq]);

  const applyStatus = useCallback(
    (next: StreamStatus) => {
      setStatus(next);
      applyStreamMeta(next.meta);
      if (next.running) {
        frameFailCount.current = 0;
        if (next.meta?.capture_seq == null) {
          lastCaptureSeq.current = undefined;
          lastCaptureSeqChangeMs.current = Date.now();
          setStreamStale(false);
        }
      }
    },
    [applyStreamMeta],
  );

  const refreshStatus = useCallback(async () => {
    const next = await window.exodia.getStreamStatus();
    applyStatus(next);
    return next;
  }, [applyStatus]);

  const streamPortUp = Boolean(status?.running);
  const streamRunning = streamPortUp && !streamStale;

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
    if (!streamPortUp) {
      setStreamImage(undefined);
      return;
    }

    let cancelled = false;
    let inFlight = false;

    const pollFrame = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        const result = await window.exodia.fetchGamePreview();
        if (cancelled) return;
        if (result.ok && result.imageDataUrl) {
          frameFailCount.current = 0;
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
  }, [streamPortUp, status?.port]);

  useEffect(() => {
    if (!streamPortUp) return;

    let cancelled = false;
    const poll = async () => {
      const result = await window.exodia.fetchStreamMeta();
      if (!cancelled && result.ok) {
        applyStreamMeta(result.meta);
      }
    };

    poll();
    const metaId = setInterval(poll, META_POLL_MS);
    const frozenId = setInterval(() => {
      if (cancelled) return;
      if (lastCaptureSeq.current == null) return;
      if (Date.now() - lastCaptureSeqChangeMs.current >= FROZEN_SEQ_STALE_MS) {
        setStreamStale(true);
      }
    }, FROZEN_SEQ_CHECK_MS);
    return () => {
      cancelled = true;
      clearInterval(metaId);
      clearInterval(frozenId);
    };
  }, [streamPortUp, status?.port, applyStreamMeta]);

  const invalidateCache = useCallback(async () => {
    await window.exodia.invalidateStreamCache();
  }, []);

  const restartStream = useCallback(async () => {
    setRestarting(true);
    setStreamImage(undefined);
    setStreamStale(false);
    frameFailCount.current = 0;
    lastCaptureSeq.current = undefined;
    lastCaptureSeqChangeMs.current = Date.now();
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
    /** HTTP stream process up (may be stale while JPEG polls still succeed). */
    streamPortUp,
    /** Port up and capture_seq advancing — safe for stream-primary actions. */
    streamRunning,
    streamStale,
    streamAttached: Boolean(status?.attached),
    streamImage,
    streamMeta,
    streamError: status?.error,
    perception,
    worldHitCount,
    restarting,
    refreshStatus,
    invalidateCache,
    restartStream,
    startStream,
  };
}
