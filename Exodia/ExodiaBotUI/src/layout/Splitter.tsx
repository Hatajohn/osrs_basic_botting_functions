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

export type PanelId = 'log' | 'tasks' | 'scripts' | 'actions';

export type DashboardLayout = {
  logPct: number;
  scriptsPct: number;
  /** Top of log column: text OCR overlay (flex weight vs log console below). */
  logTextFlex: number;
  tasksFlex: number;
  actionsFlex: number;
  collapsed: Record<PanelId, boolean>;
  hidden: Record<PanelId, boolean>;
};

/** Bumped when layout shape or defaults change — triggers merge + sanitize on load. */
export const DASHBOARD_LAYOUT_VERSION = 8;

const STORAGE_KEY = 'exodia-dashboard-layout-v8';
const STORAGE_KEY_V7 = 'exodia-dashboard-layout-v7';
const STORAGE_KEY_V6 = 'exodia-dashboard-layout-v6';
const STORAGE_KEY_V5 = 'exodia-dashboard-layout-v5';
const STORAGE_KEY_V4 = 'exodia-dashboard-layout-v4';

const DEFAULT_COLLAPSED: Record<PanelId, boolean> = {
  log: false,
  tasks: false,
  scripts: false,
  actions: false,
};

const DEFAULT_HIDDEN: Record<PanelId, boolean> = {
  log: false,
  tasks: false,
  scripts: false,
  actions: false,
};

const DEFAULT_LAYOUT: DashboardLayout = {
  logPct: 18,
  scriptsPct: 22,
  logTextFlex: 50,
  tasksFlex: 28,
  actionsFlex: 38,
  collapsed: { ...DEFAULT_COLLAPSED },
  hidden: { ...DEFAULT_HIDDEN },
};

const COLLAPSED_STRIP_PX = 40;
const COLLAPSED_HEADER_PX = 36;

const MIN_SIDE = 12;
const MAX_SIDE = 48;
const MIN_CENTER = 24;
const MIN_LOG_TEXT_FLEX = 18;
const MAX_LOG_TEXT_FLEX = 82;
const MIN_TASKS_FLEX = 12;
const MAX_TASKS_FLEX = 55;
const MIN_ACTIONS_FLEX = 20;
const MAX_ACTIONS_FLEX = 65;

function loadCollapsed(parsed: Partial<DashboardLayout>): Record<PanelId, boolean> {
  return {
    log: parsed.collapsed?.log ?? DEFAULT_COLLAPSED.log,
    tasks: parsed.collapsed?.tasks ?? DEFAULT_COLLAPSED.tasks,
    scripts: parsed.collapsed?.scripts ?? DEFAULT_COLLAPSED.scripts,
    actions: parsed.collapsed?.actions ?? DEFAULT_COLLAPSED.actions,
  };
}

function loadHidden(parsed: Partial<DashboardLayout>): Record<PanelId, boolean> {
  const hidden = {
    log: parsed.hidden?.log ?? DEFAULT_HIDDEN.log,
    tasks: parsed.hidden?.tasks ?? DEFAULT_HIDDEN.tasks,
    scripts: parsed.hidden?.scripts ?? DEFAULT_HIDDEN.scripts,
    actions: parsed.hidden?.actions ?? DEFAULT_HIDDEN.actions,
  };
  // Recover from stuck "client only" where every panel was hidden.
  if (Object.values(hidden).every(Boolean)) {
    return { ...DEFAULT_HIDDEN };
  }
  return hidden;
}

function coerceNumber(value: unknown, fallback: number, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return fallback;
  }
  return clamp(value, min, max);
}

/** Clamp persisted numbers so panes never get 0% width/height from bad or legacy storage. */
export function sanitizeDashboardLayout(parsed: Partial<DashboardLayout>): DashboardLayout {
  return {
    logPct: coerceNumber(parsed.logPct, DEFAULT_LAYOUT.logPct, MIN_SIDE, MAX_SIDE),
    scriptsPct: coerceNumber(parsed.scriptsPct, DEFAULT_LAYOUT.scriptsPct, MIN_SIDE, MAX_SIDE),
    logTextFlex: coerceNumber(parsed.logTextFlex, DEFAULT_LAYOUT.logTextFlex, MIN_LOG_TEXT_FLEX, MAX_LOG_TEXT_FLEX),
    tasksFlex: coerceNumber(parsed.tasksFlex, DEFAULT_LAYOUT.tasksFlex, MIN_TASKS_FLEX, MAX_TASKS_FLEX),
    actionsFlex: coerceNumber(parsed.actionsFlex, DEFAULT_LAYOUT.actionsFlex, MIN_ACTIONS_FLEX, MAX_ACTIONS_FLEX),
    collapsed: loadCollapsed(parsed),
    hidden: loadHidden(parsed),
  };
}

type StoredDashboardLayout = Partial<DashboardLayout> & { version?: number };

function loadLayout(): DashboardLayout {
  try {
    const raw =
      localStorage.getItem(STORAGE_KEY) ??
      localStorage.getItem(STORAGE_KEY_V7) ??
      localStorage.getItem(STORAGE_KEY_V6) ??
      localStorage.getItem(STORAGE_KEY_V5) ??
      localStorage.getItem(STORAGE_KEY_V4);
    if (!raw) return { ...DEFAULT_LAYOUT };
    const parsed = JSON.parse(raw) as StoredDashboardLayout;
    const needsLegacyMerge =
      parsed.version == null || parsed.version < DASHBOARD_LAYOUT_VERSION || parsed.logTextFlex == null;
    const merged: Partial<DashboardLayout> = needsLegacyMerge
      ? {
          ...DEFAULT_LAYOUT,
          ...parsed,
          collapsed: { ...DEFAULT_COLLAPSED, ...parsed.collapsed },
          hidden: { ...DEFAULT_HIDDEN, ...parsed.hidden },
        }
      : parsed;
    return sanitizeDashboardLayout(merged);
  } catch {
    return { ...DEFAULT_LAYOUT };
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function paneFlex(value: number): string {
  return `${value} 1 0`;
}

function fixedFlex(px: number): string {
  return `0 0 ${px}px`;
}

export function useDashboardLayout(containerRef: React.RefObject<HTMLElement | null>) {
  const [layout, setLayout] = useState<DashboardLayout>(() => sanitizeDashboardLayout(loadLayout()));

  useEffect(() => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...layout, version: DASHBOARD_LAYOUT_VERSION }),
    );
  }, [layout]);

  const togglePanelCollapsed = useCallback((id: PanelId) => {
    setLayout((prev) => ({
      ...prev,
      collapsed: { ...prev.collapsed, [id]: !prev.collapsed[id] },
    }));
  }, []);

  const togglePanelHidden = useCallback((id: PanelId) => {
    setLayout((prev) => ({
      ...prev,
      hidden: { ...prev.hidden, [id]: !prev.hidden[id] },
    }));
  }, []);

  const setPanelCollapsed = useCallback((id: PanelId, value: boolean) => {
    setLayout((prev) => ({
      ...prev,
      collapsed: { ...prev.collapsed, [id]: value },
    }));
  }, []);

  const setPanelHidden = useCallback((id: PanelId, value: boolean) => {
    setLayout((prev) => ({
      ...prev,
      hidden: { ...prev.hidden, [id]: value },
    }));
  }, []);

  const toggleClientOnly = useCallback(() => {
    setLayout((prev) => {
      const allHidden = Object.values(prev.hidden).every(Boolean);
      return {
        ...prev,
        hidden: allHidden ? { ...DEFAULT_HIDDEN } : { log: true, tasks: true, scripts: true, actions: true },
      };
    });
  }, []);

  const { collapsed, hidden } = layout;
  const logCollapsed = collapsed.log;
  const tasksCollapsed = collapsed.tasks;
  const scriptsCollapsed = collapsed.scripts;
  const actionsCollapsed = collapsed.actions;
  const logHidden = hidden.log;
  const tasksHidden = hidden.tasks;
  const scriptsHidden = hidden.scripts;
  const actionsHidden = hidden.actions;
  const rightStripCollapsed = scriptsCollapsed && actionsCollapsed;
  const rightColumnHidden = scriptsHidden && actionsHidden;

  const logPct = coerceNumber(layout.logPct, DEFAULT_LAYOUT.logPct, MIN_SIDE, MAX_SIDE);
  const scriptsPct = coerceNumber(layout.scriptsPct, DEFAULT_LAYOUT.scriptsPct, MIN_SIDE, MAX_SIDE);
  const logTextFlex = coerceNumber(layout.logTextFlex, DEFAULT_LAYOUT.logTextFlex, MIN_LOG_TEXT_FLEX, MAX_LOG_TEXT_FLEX);
  const tasksFlex = coerceNumber(layout.tasksFlex, DEFAULT_LAYOUT.tasksFlex, MIN_TASKS_FLEX, MAX_TASKS_FLEX);
  const actionsFlex = coerceNumber(layout.actionsFlex, DEFAULT_LAYOUT.actionsFlex, MIN_ACTIONS_FLEX, MAX_ACTIONS_FLEX);

  const centerPct = 100 - logPct - scriptsPct;
  const logConsoleFlex = 100 - logTextFlex;
  const runeliteFlex = tasksCollapsed || tasksHidden ? 100 : 100 - tasksFlex;
  const scriptsColumnFlex = actionsCollapsed || actionsHidden ? 100 : 100 - actionsFlex;

  // When a side column is hidden or collapsed to a strip, give its flex weight to the center.
  const centerFlexWeight =
    centerPct +
    (logCollapsed || logHidden ? logPct : 0) +
    (rightStripCollapsed || rightColumnHidden ? scriptsPct : 0);

  const effectiveLogFlex = logHidden
    ? '0 0 0'
    : logCollapsed
      ? fixedFlex(COLLAPSED_STRIP_PX)
      : paneFlex(logPct);
  const effectiveLogTextFlex = paneFlex(logTextFlex);
  const effectiveLogConsoleFlex = paneFlex(logConsoleFlex);
  const effectiveCenterFlex = paneFlex(centerFlexWeight);
  const effectiveScriptsColumnFlex = rightColumnHidden
    ? '0 0 0'
    : rightStripCollapsed
      ? fixedFlex(COLLAPSED_STRIP_PX)
      : paneFlex(scriptsPct);
  const effectiveRuneliteFlex = tasksHidden || tasksCollapsed ? '1 1 0' : paneFlex(runeliteFlex);
  const effectiveTasksFlex = tasksHidden
    ? '0 0 0'
    : tasksCollapsed
      ? fixedFlex(COLLAPSED_HEADER_PX)
      : paneFlex(tasksFlex);
  const effectiveScriptsFlex = rightColumnHidden
    ? '0 0 0'
    : rightStripCollapsed
      ? '1 1 0'
      : scriptsHidden
        ? '0 0 0'
        : scriptsCollapsed
          ? fixedFlex(COLLAPSED_HEADER_PX)
          : actionsHidden
            ? '1 1 0'
            : paneFlex(scriptsColumnFlex);
  const effectiveActionsFlex = rightColumnHidden
    ? '0 0 0'
    : rightStripCollapsed
      ? '1 1 0'
      : actionsHidden
        ? '0 0 0'
        : actionsCollapsed
          ? fixedFlex(COLLAPSED_HEADER_PX)
          : scriptsHidden
            ? '1 1 0'
            : paneFlex(actionsFlex);

  const applyHorizontalDelta = useCallback(
    (deltaPx: number, sign: 1 | -1, field: 'logPct' | 'scriptsPct') => {
      const width = containerRef.current?.clientWidth ?? 1;
      const deltaPct = sign * (deltaPx / width) * 100;
      setLayout((prev) => {
        const scriptsPct = coerceNumber(prev.scriptsPct, DEFAULT_LAYOUT.scriptsPct, MIN_SIDE, MAX_SIDE);
        if (field === 'logPct') {
          const maxLog = Math.min(MAX_SIDE, 100 - MIN_CENTER - scriptsPct);
          return {
            ...prev,
            logPct: clamp(prev.logPct + deltaPct, MIN_SIDE, maxLog),
            scriptsPct,
          };
        }
        const logPct = coerceNumber(prev.logPct, DEFAULT_LAYOUT.logPct, MIN_SIDE, MAX_SIDE);
        const maxScripts = Math.min(MAX_SIDE, 100 - MIN_CENTER - logPct);
        return {
          ...prev,
          logPct,
          scriptsPct: clamp(prev.scriptsPct + deltaPct, MIN_SIDE, maxScripts),
        };
      });
    },
    [containerRef],
  );

  const applyVerticalDelta = useCallback(
    (
      deltaPx: number,
      sign: 1 | -1,
      field: 'logTextFlex' | 'tasksFlex' | 'actionsFlex',
      containerSelector: '.dashboard__log-column' | '.dashboard__center' | '.dashboard__right',
    ) => {
      const height =
        containerRef.current?.querySelector<HTMLElement>(containerSelector)?.clientHeight ?? 1;
      const deltaFlex = sign * (deltaPx / height) * 100;
      setLayout((prev) => {
        if (field === 'logTextFlex') {
          return {
            ...prev,
            logTextFlex: clamp(prev.logTextFlex + deltaFlex, MIN_LOG_TEXT_FLEX, MAX_LOG_TEXT_FLEX),
          };
        }
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

  /** Log column: drag down enlarges Log console (bottom pane). */
  const resizeLogText = useCallback(
    (deltaPx: number) => applyVerticalDelta(deltaPx, -1, 'logTextFlex', '.dashboard__log-column'),
    [applyVerticalDelta],
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
    togglePanelCollapsed,
    togglePanelHidden,
    setPanelCollapsed,
    setPanelHidden,
    toggleClientOnly,
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
  };
}
