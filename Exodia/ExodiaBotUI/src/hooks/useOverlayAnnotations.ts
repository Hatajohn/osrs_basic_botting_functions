import { useCallback, useEffect, useRef, useState } from 'react';
import type { ActionClickPreview } from '../../shared/ipc';

export const DEFAULT_OVERLAY_TTL_MS = 1000;
export const DEFAULT_OVERLAY_FADE_MS = 2000;

export type OverlayAnnotationEntry = {
  id: string;
  preview: ActionClickPreview;
  createdAt: number;
  ttlMs: number;
  fadeMs: number;
  /** When true, marker stays visible until cleared or refreshed (confirm dialog pending). */
  hold: boolean;
  opacity: number;
};

export type PushAnnotationOpts = {
  ttlMs?: number;
  fadeMs?: number;
  /** Clear existing annotations with the same blockId before pushing. Default true. */
  replaceGroup?: boolean;
  /** Keep visible until clearGroup / refreshGroup (dry-run awaiting confirm). */
  hold?: boolean;
};

export type RefreshGroupOpts = {
  ttlMs?: number;
  fadeMs?: number;
};

function nextId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `ann-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function computeOpacity(entry: OverlayAnnotationEntry, now: number): number | null {
  if (entry.hold) return 1;
  const age = now - entry.createdAt;
  if (age < entry.ttlMs) return 1;
  const fadeProgress = (age - entry.ttlMs) / entry.fadeMs;
  if (fadeProgress >= 1) return null;
  return 1 - fadeProgress;
}

export function useOverlayAnnotations() {
  const [annotations, setAnnotations] = useState<OverlayAnnotationEntry[]>([]);
  const annotationsRef = useRef(annotations);
  annotationsRef.current = annotations;

  const pushAnnotation = useCallback((preview: ActionClickPreview, opts?: PushAnnotationOpts) => {
    const replaceGroup = opts?.replaceGroup !== false;
    const hold = opts?.hold ?? false;
    const ttlMs = opts?.ttlMs ?? DEFAULT_OVERLAY_TTL_MS;
    const fadeMs = opts?.fadeMs ?? DEFAULT_OVERLAY_FADE_MS;
    const id = nextId();
    const createdAt = Date.now();

    setAnnotations((prev) => {
      const kept = replaceGroup ? prev.filter((a) => a.preview.blockId !== preview.blockId) : prev;
      return [
        ...kept,
        {
          id,
          preview,
          createdAt,
          ttlMs,
          fadeMs,
          hold,
          opacity: 1,
        },
      ];
    });

    return id;
  }, []);

  const clearGroup = useCallback((blockId: string) => {
    setAnnotations((prev) => prev.filter((a) => a.preview.blockId !== blockId));
  }, []);

  const clearAll = useCallback(() => {
    setAnnotations([]);
  }, []);

  const refreshGroup = useCallback(
    (blockId: string, opts?: RefreshGroupOpts) => {
      const now = Date.now();
      setAnnotations((prev) =>
        prev.map((entry) => {
          if (entry.preview.blockId !== blockId) return entry;
          return {
            ...entry,
            hold: false,
            createdAt: now,
            ttlMs: opts?.ttlMs ?? entry.ttlMs,
            fadeMs: opts?.fadeMs ?? entry.fadeMs,
            opacity: 1,
          };
        }),
      );
    },
    [],
  );

  const latestPreview = annotations.length > 0 ? annotations[annotations.length - 1].preview : null;

  useEffect(() => {
    let raf = 0;

    const tick = () => {
      const now = Date.now();
      const current = annotationsRef.current;
      if (current.length === 0) {
        raf = requestAnimationFrame(tick);
        return;
      }

      let changed = false;
      const next: OverlayAnnotationEntry[] = [];

      for (const entry of current) {
        const opacity = computeOpacity(entry, now);
        if (opacity == null) {
          changed = true;
          continue;
        }
        if (opacity !== entry.opacity) {
          changed = true;
          next.push({ ...entry, opacity });
        } else {
          next.push(entry);
        }
      }

      if (changed) {
        setAnnotations(next);
      }

      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return {
    annotations,
    latestPreview,
    pushAnnotation,
    clearGroup,
    clearAll,
    refreshGroup,
  };
}
