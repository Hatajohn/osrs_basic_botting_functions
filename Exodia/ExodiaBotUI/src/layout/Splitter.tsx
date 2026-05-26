import { useCallback, useEffect, useRef, useState } from 'react';
import './Splitter.css';

type SplitterProps = {
  orientation: 'horizontal' | 'vertical';
  onDrag: (deltaPx: number) => void;
};

export function Splitter({ orientation, onDrag }: SplitterProps) {
  const onDragRef = useRef(onDrag);
  onDragRef.current = onDrag;

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);

    let lastPos = orientation === 'vertical' ? e.clientX : e.clientY;
    document.body.classList.add('dashboard--dragging');
    document.body.style.cursor = orientation === 'vertical' ? 'col-resize' : 'row-resize';

    const onMove = (ev: PointerEvent) => {
      const pos = orientation === 'vertical' ? ev.clientX : ev.clientY;
      const delta = pos - lastPos;
      if (delta !== 0) {
        onDragRef.current(delta);
        lastPos = pos;
      }
    };

    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      document.removeEventListener('pointercancel', onUp);
      document.body.classList.remove('dashboard--dragging');
      document.body.style.cursor = '';
      if (handle.hasPointerCapture(e.pointerId)) {
        handle.releasePointerCapture(e.pointerId);
      }
    };

    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onUp);
  };

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={`splitter splitter--${orientation}`}
      onPointerDown={onPointerDown}
    />
  );
}

export type DashboardLayout = {
  logPct: number;
  scriptsPct: number;
  tasksFlex: number;
  actionsFlex: number;
};

const STORAGE_KEY = 'exodia-dashboard-layout-v4';
const DEFAULT_LAYOUT: DashboardLayout = {
  logPct: 18,
  scriptsPct: 22,
  tasksFlex: 28,
  actionsFlex: 38,
};

const MIN_SIDE = 12;
const MAX_SIDE = 48;
const MIN_CENTER = 24;
const MIN_TASKS_FLEX = 12;
const MAX_TASKS_FLEX = 55;
const MIN_ACTIONS_FLEX = 20;
const MAX_ACTIONS_FLEX = 65;

function loadLayout(): DashboardLayout {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<DashboardLayout>;
    return {
      logPct: parsed.logPct ?? DEFAULT_LAYOUT.logPct,
      scriptsPct: parsed.scriptsPct ?? DEFAULT_LAYOUT.scriptsPct,
      tasksFlex: parsed.tasksFlex ?? DEFAULT_LAYOUT.tasksFlex,
      actionsFlex: parsed.actionsFlex ?? DEFAULT_LAYOUT.actionsFlex,
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function paneFlex(value: number): string {
  return `${value} 1 0`;
}

export function useDashboardLayout(containerRef: React.RefObject<HTMLElement | null>) {
  const [layout, setLayout] = useState<DashboardLayout>(loadLayout);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  }, [layout]);

  const centerPct = 100 - layout.logPct - layout.scriptsPct;
  const runeliteFlex = 100 - layout.tasksFlex;
  const scriptsColumnFlex = 100 - layout.actionsFlex;

  const applyHorizontalDelta = useCallback(
    (deltaPx: number, sign: 1 | -1, field: 'logPct' | 'scriptsPct') => {
      const width = containerRef.current?.clientWidth ?? 1;
      const deltaPct = sign * (deltaPx / width) * 100;
      setLayout((prev) => {
        if (field === 'logPct') {
          const maxLog = Math.min(MAX_SIDE, 100 - MIN_CENTER - prev.scriptsPct);
          return { ...prev, logPct: clamp(prev.logPct + deltaPct, MIN_SIDE, maxLog) };
        }
        const maxScripts = Math.min(MAX_SIDE, 100 - MIN_CENTER - prev.logPct);
        return { ...prev, scriptsPct: clamp(prev.scriptsPct + deltaPct, MIN_SIDE, maxScripts) };
      });
    },
    [containerRef],
  );

  const applyVerticalDelta = useCallback(
    (
      deltaPx: number,
      sign: 1 | -1,
      field: 'tasksFlex' | 'actionsFlex',
      containerSelector: '.dashboard__center' | '.dashboard__right',
    ) => {
      const height =
        containerRef.current?.querySelector<HTMLElement>(containerSelector)?.clientHeight ?? 1;
      const deltaFlex = sign * (deltaPx / height) * 100;
      setLayout((prev) => {
        if (field === 'tasksFlex') {
          return {
            ...prev,
            tasksFlex: clamp(prev.tasksFlex + deltaFlex, MIN_TASKS_FLEX, MAX_TASKS_FLEX),
          };
        }
        return {
          ...prev,
          actionsFlex: clamp(prev.actionsFlex + deltaFlex, MIN_ACTIONS_FLEX, MAX_ACTIONS_FLEX),
        };
      });
    },
    [containerRef],
  );

  /** Log splitter: drag right enlarges Log (left pane). */
  const resizeLog = useCallback(
    (deltaPx: number) => applyHorizontalDelta(deltaPx, 1, 'logPct'),
    [applyHorizontalDelta],
  );

  /** Scripts column splitter: drag left enlarges Scripts (right pane). */
  const resizeScripts = useCallback(
    (deltaPx: number) => applyHorizontalDelta(deltaPx, -1, 'scriptsPct'),
    [applyHorizontalDelta],
  );

  /** Center stack: drag down enlarges Bot tasks (bottom pane). */
  const resizeTasks = useCallback(
    (deltaPx: number) => applyVerticalDelta(deltaPx, -1, 'tasksFlex', '.dashboard__center'),
    [applyVerticalDelta],
  );

  /** Right stack: drag down enlarges Actions (bottom pane). */
  const resizeActions = useCallback(
    (deltaPx: number) => applyVerticalDelta(deltaPx, -1, 'actionsFlex', '.dashboard__right'),
    [applyVerticalDelta],
  );

  return {
    layout,
    centerPct,
    runeliteFlex,
    scriptsColumnFlex,
    paneFlex,
    resizeLog,
    resizeScripts,
    resizeTasks,
    resizeActions,
  };
}
