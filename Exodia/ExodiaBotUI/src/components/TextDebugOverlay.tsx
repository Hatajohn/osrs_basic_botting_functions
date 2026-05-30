import { useMemo, useRef } from 'react';
import type { StreamMeta, TextPerceptionMeta, TextSpanMeta } from '../../shared/ipc';
import './TextDebugOverlay.css';

const COLOR_SWATCH: Record<string, string> = {
  green: '#22c55e',
  red: '#ef4444',
  yellow: '#eab308',
  cyan: '#22d3ee',
  orange: '#f97316',
  white: '#f8fafc',
  unknown: '#94a3b8',
};

function swatchForColor(color: string): string {
  return COLOR_SWATCH[color.toLowerCase()] ?? COLOR_SWATCH.unknown!;
}

function resolveColor(a: string, b: string): string {
  if (a === b) return a;
  if (a === 'unknown') return b;
  if (b === 'unknown') return a;
  return a;
}

function unionBbox(a: number[], b: number[]): number[] {
  const [ax, ay, aw, ah] = a;
  const [bx, by, bw, bh] = b;
  const x1 = Math.min(ax, bx);
  const y1 = Math.min(ay, by);
  const x2 = Math.max(ax + aw, bx + bw);
  const y2 = Math.max(ay + ah, by + bh);
  return [x1, y1, x2 - x1, y2 - y1];
}

function shouldMergeSpans(a: TextSpanMeta, b: TextSpanMeta): boolean {
  const [ax, ay, aw, ah] = a.bbox ?? [0, 0, 0, 0];
  const [bx, by, bw, bh] = b.bbox ?? [0, 0, 0, 0];
  const lineH = Math.max(ah, bh, 1);
  const acy = ay + ah * 0.5;
  const bcy = by + bh * 0.5;
  if (Math.abs(acy - bcy) > lineH * 0.55) return false;
  const gap = bx - (ax + aw);
  if (gap > lineH * 4 || gap < -lineH * 0.6) return false;
  const ca = a.color.toLowerCase();
  const cb = b.color.toLowerCase();
  if (ca !== cb && ca !== 'unknown' && cb !== 'unknown') return false;
  return true;
}

function mergeTwoSpans(a: TextSpanMeta, b: TextSpanMeta): TextSpanMeta {
  const sep = a.text.endsWith(' ') || b.text.startsWith(' ') ? '' : ' ';
  const confA = a.conf ?? 0;
  const confB = b.conf ?? 0;
  const conf = confA > 0 && confB > 0 ? Math.min(confA, confB) : Math.max(confA, confB);
  return {
    text: a.text + sep + b.text,
    color: resolveColor(a.color, b.color),
    bbox: unionBbox(a.bbox ?? [0, 0, 0, 0], b.bbox ?? [0, 0, 0, 0]),
    conf,
  };
}

/** Join per-word OCR rows on the same line (e.g. ``Not`` + ``fishing``). */
function mergeSpansForDisplay(spans: TextSpanMeta[]): TextSpanMeta[] {
  if (spans.length < 2) return spans;
  const ordered = [...spans].sort((a, b) => {
    const ay = a.bbox?.[1] ?? 0;
    const by = b.bbox?.[1] ?? 0;
    if (ay !== by) return ay - by;
    return (a.bbox?.[0] ?? 0) - (b.bbox?.[0] ?? 0);
  });
  const merged: TextSpanMeta[] = [ordered[0]!];
  for (let i = 1; i < ordered.length; i += 1) {
    const span = ordered[i]!;
    const prev = merged[merged.length - 1]!;
    if (shouldMergeSpans(prev, span)) {
      merged[merged.length - 1] = mergeTwoSpans(prev, span);
    } else {
      merged.push(span);
    }
  }
  return merged;
}

/** When HSV misses OSRS salmon text, infer skilling-line color from wording. */
function inferDisplayColor(text: string, color: string): string {
  const key = color.toLowerCase();
  if (key !== 'unknown') return key;
  const norm = text.toLowerCase().replace(/\s+/g, ' ');
  if (/\bnot\b/.test(norm) && /fish/.test(norm)) return 'red';
  if (/fish/.test(norm) && !/\bnot\b/.test(norm)) return 'green';
  return key;
}

function spansForList(text: TextPerceptionMeta | undefined): TextSpanMeta[] {
  if (!text) return [];
  const raw =
    text.spans && text.spans.length > 0 ? text.spans : (text.fishing_spans ?? []);
  const merged = mergeSpansForDisplay(raw);
  return merged.map((span) => ({
    ...span,
    color: inferDisplayColor(span.text, span.color),
  }));
}

/** Stable row identity: display color + OCR string (bbox kept on span for bots via /meta). */
export function spanRowKey(span: TextSpanMeta): string {
  return `${span.color.toLowerCase()}\t${span.text}`;
}

/**
 * Keep prior order when color+text still appear; append new rows; drop missing rows.
 */
export function reconcileStableSpanList(
  previous: TextSpanMeta[],
  incoming: TextSpanMeta[],
): TextSpanMeta[] {
  const used = new Set<number>();
  const next: TextSpanMeta[] = [];
  const keysInNext = new Set<string>();

  for (const row of previous) {
    const key = spanRowKey(row);
    const idx = incoming.findIndex((s, i) => !used.has(i) && spanRowKey(s) === key);
    if (idx >= 0) {
      used.add(idx);
      next.push(incoming[idx]!);
      keysInNext.add(key);
    }
  }

  for (let i = 0; i < incoming.length; i += 1) {
    if (used.has(i)) continue;
    const span = incoming[i]!;
    const key = spanRowKey(span);
    if (keysInNext.has(key)) continue;
    used.add(i);
    next.push(span);
    keysInNext.add(key);
  }

  return next;
}

type TextDebugOverlayProps = {
  streamMeta: StreamMeta | null | undefined;
  streamPortUp?: boolean;
};

export function TextDebugOverlay({ streamMeta, streamPortUp }: TextDebugOverlayProps) {
  const textMeta = streamMeta?.perception?.text;
  const incoming = useMemo(() => spansForList(textMeta), [textMeta]);
  const stableRef = useRef<TextSpanMeta[]>([]);

  const spans = useMemo(() => {
    if (!streamPortUp) {
      stableRef.current = [];
      return [];
    }
    const next = reconcileStableSpanList(stableRef.current, incoming);
    stableRef.current = next;
    return next;
  }, [incoming, streamPortUp]);

  const stats = useMemo(() => {
    const listed = spans.length;
    const total = textMeta?.span_count ?? listed;
    const seq = textMeta?.processed_seq ?? textMeta?.capture_seq;
    const scan = textMeta?.scan_ms;
    const fps = textMeta?.vision_fps;
    const parts: string[] = [];
    parts.push(`${listed} listed`);
    if (total !== listed) parts.push(`${total} in meta`);
    if (seq != null) parts.push(`seq ${seq}`);
    if (scan != null) parts.push(`${scan.toFixed(0)} ms`);
    if (fps != null) parts.push(`${fps.toFixed(1)} fps`);
    return parts.join(' · ');
  }, [textMeta, spans.length]);

  const sourceNote = useMemo(() => {
    if (!textMeta) return null;
    if (textMeta.spans && textMeta.spans.length > 0) return null;
    if (textMeta.fishing_spans && textMeta.fishing_spans.length > 0) {
      return 'Showing fishing_spans only (enable EXODIA_TEXT_META_FULL=1 for full client text).';
    }
    if ((textMeta.span_count ?? 0) > 0) {
      return 'Meta reports spans but none were included in /meta — enable EXODIA_TEXT_META_FULL=1.';
    }
    return null;
  }, [textMeta]);

  return (
    <div className="text-span-list">
      <div className="text-span-list__toolbar">
        <span className="text-span-list__stats">{stats || 'No text meta'}</span>
      </div>
      <div className="text-span-list__scroll">
        {!streamPortUp ? (
          <p className="text-span-list__empty">Start the perception stream to list on-screen text.</p>
        ) : spans.length === 0 ? (
          <p className="text-span-list__empty">
            {sourceNote ?? 'No OCR spans yet — wait for the text worker or check EXODIA_TEXT_VISION=1.'}
          </p>
        ) : (
          <table className="text-span-list__table">
            <thead>
              <tr>
                <th scope="col">Color</th>
                <th scope="col">Text</th>
                <th scope="col" className="text-span-list__num">
                  Conf
                </th>
              </tr>
            </thead>
            <tbody>
              {spans.map((span) => (
                <tr key={spanRowKey(span)}>
                  <td>
                    <span
                      className="text-span-list__color"
                      style={{ color: swatchForColor(span.color) }}
                      title={span.color}
                    >
                      {span.color}
                    </span>
                  </td>
                  <td className="text-span-list__text">{span.text}</td>
                  <td className="text-span-list__num">
                    {span.conf != null ? `${Math.round(span.conf)}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {sourceNote && spans.length > 0 ? (
          <p className="text-span-list__note">{sourceNote}</p>
        ) : null}
      </div>
    </div>
  );
}
