import type { DebugFrameMode } from '../../shared/ipc';

export type EnabledWhen =
  | 'always'
  | 'never'
  | 'botRunning'
  | 'chainDirty'
  | 'previewLive'
  | 'hasDebugFrame';

export type MenuContext = {
  botRunning: boolean;
  chainDirty: boolean;
  previewLive: boolean;
  hasDebugFrame: boolean;
  debugMode: DebugFrameMode;
};

export type MenuActionId =
  | 'clearLog'
  | 'preferences'
  | 'saveSession'
  | 'saveChain'
  | 'openChain'
  | 'exportLog'
  | 'quit'
  | 'botStop'
  | 'botPause'
  | 'botResume'
  | 'startWithSession'
  | 'refreshDebugFrame'
  | 'saveSnapshot'
  | 'debugModeInventoryIdentify'
  | 'debugModeRawClient'
  | 'debugModeGrid'
  | 'previewFps'
  | 'overlayLayers'
  | 'togglePlayByPlay'
  | 'tools'
  | 'about'
  | 'openLogsFolder';

export type MenuItemDef = {
  id: MenuActionId;
  label: string;
  shortcut?: string;
  enabledWhen?: EnabledWhen;
  phase?: number;
  stubMessage?: string;
  radioGroup?: string;
};

export type MenuDef = {
  id: string;
  label: string;
  items: MenuItemDef[];
};

export const MENUS: MenuDef[] = [
  {
    id: 'file',
    label: 'File',
    items: [
      { id: 'clearLog', label: 'Clear log', enabledWhen: 'always', phase: 0 },
      { id: 'preferences', label: 'Preferences…', shortcut: 'Ctrl+,', enabledWhen: 'always', phase: 0 },
      {
        id: 'saveSession',
        label: 'Save session snapshot…',
        enabledWhen: 'never',
        phase: 2,
        stubMessage: 'Not available yet (Phase 2)',
      },
      {
        id: 'saveChain',
        label: 'Save chain…',
        enabledWhen: 'never',
        phase: 3,
        stubMessage: 'Not available yet (Phase 3)',
      },
      {
        id: 'openChain',
        label: 'Open chain…',
        enabledWhen: 'never',
        phase: 3,
        stubMessage: 'Not available yet (Phase 3)',
      },
      {
        id: 'exportLog',
        label: 'Export log…',
        enabledWhen: 'never',
        phase: 3,
        stubMessage: 'Not available yet (Phase 3)',
      },
      { id: 'quit', label: 'Quit', shortcut: 'Ctrl+Q', enabledWhen: 'always', phase: 0 },
    ],
  },
  {
    id: 'bot',
    label: 'Bot',
    items: [
      {
        id: 'botStop',
        label: 'Stop',
        enabledWhen: 'botRunning',
        phase: 2,
      },
      {
        id: 'botPause',
        label: 'Pause',
        enabledWhen: 'botRunning',
        phase: 2,
      },
      {
        id: 'botResume',
        label: 'Resume',
        enabledWhen: 'botRunning',
        phase: 2,
      },
      {
        id: 'startWithSession',
        label: 'Start with session sidecars',
        enabledWhen: 'never',
        phase: 7,
        stubMessage: 'Not available yet (Phase 7)',
      },
    ],
  },
  {
    id: 'view',
    label: 'View',
    items: [
      {
        id: 'refreshDebugFrame',
        label: 'Refresh debug frame',
        shortcut: 'F5',
        enabledWhen: 'always',
        phase: 1,
      },
      {
        id: 'saveSnapshot',
        label: 'Save RuneLite snapshot',
        enabledWhen: 'hasDebugFrame',
        phase: 1,
        stubMessage: 'Refresh a debug frame first',
      },
      {
        id: 'debugModeInventoryIdentify',
        label: 'Inventory identify',
        enabledWhen: 'always',
        phase: 1,
        radioGroup: 'debugMode',
      },
      {
        id: 'debugModeRawClient',
        label: 'Raw client',
        enabledWhen: 'always',
        phase: 1,
        radioGroup: 'debugMode',
      },
      {
        id: 'debugModeGrid',
        label: 'Grid only',
        enabledWhen: 'always',
        phase: 1,
        radioGroup: 'debugMode',
      },
      {
        id: 'previewFps',
        label: 'Preview FPS (0.5 / 1 / 2)',
        enabledWhen: 'never',
        phase: 2,
        stubMessage: 'Not available yet (Phase 2)',
      },
      {
        id: 'overlayLayers',
        label: 'Overlay layers…',
        enabledWhen: 'never',
        phase: 5,
        stubMessage: 'Not available yet (Phase 5)',
      },
      {
        id: 'togglePlayByPlay',
        label: 'Show play-by-play in Log',
        enabledWhen: 'never',
        phase: 5,
        stubMessage: 'Not available yet (Phase 5)',
      },
    ],
  },
  {
    id: 'tools',
    label: 'Tools',
    items: [
      {
        id: 'tools',
        label: 'Utilities…',
        enabledWhen: 'never',
        phase: 6,
        stubMessage: 'Not available yet (Phase 6)',
      },
    ],
  },
  {
    id: 'help',
    label: 'Help',
    items: [
      { id: 'about', label: 'About Exodia', enabledWhen: 'always', phase: 0 },
      {
        id: 'openLogsFolder',
        label: 'Open logs folder',
        enabledWhen: 'always',
        phase: 1,
      },
    ],
  },
];

export function isMenuItemEnabled(
  item: MenuItemDef,
  ctx: MenuContext,
): boolean {
  const rule = item.enabledWhen ?? 'never';
  switch (rule) {
    case 'always':
      return true;
    case 'never':
      return false;
    case 'botRunning':
      return ctx.botRunning;
    case 'chainDirty':
      return ctx.chainDirty;
    case 'previewLive':
      return ctx.previewLive;
    case 'hasDebugFrame':
      return ctx.hasDebugFrame;
    default:
      return false;
  }
}

/** Phase 0 enabled items regardless of enabledWhen stub rules. */
export const PHASE0_ENABLED = new Set<MenuActionId>([
  'clearLog',
  'preferences',
  'quit',
  'about',
]);

/** Phase 1 enabled items. */
export const PHASE1_ENABLED = new Set<MenuActionId>([
  'refreshDebugFrame',
  'saveSnapshot',
  'debugModeInventoryIdentify',
  'debugModeRawClient',
  'debugModeGrid',
  'openLogsFolder',
]);

/** Phase 2 enabled items. */
export const PHASE2_ENABLED = new Set<MenuActionId>([
  'botStop',
  'botPause',
  'botResume',
]);

export function isItemInteractive(item: MenuItemDef, ctx: MenuContext): boolean {
  if (PHASE0_ENABLED.has(item.id)) return true;
  if (PHASE1_ENABLED.has(item.id)) return isMenuItemEnabled(item, ctx);
  if (PHASE2_ENABLED.has(item.id)) return isMenuItemEnabled(item, ctx);
  return isMenuItemEnabled(item, ctx);
}

export function debugModeForAction(actionId: MenuActionId): DebugFrameMode | null {
  switch (actionId) {
    case 'debugModeInventoryIdentify':
      return 'inventory_identify';
    case 'debugModeRawClient':
      return 'raw_client';
    case 'debugModeGrid':
      return 'inventory_grid';
    default:
      return null;
  }
}

export function isDebugModeSelected(mode: DebugFrameMode, actionId: MenuActionId): boolean {
  return debugModeForAction(actionId) === mode;
}

export function menuLabelForDebugMode(mode: DebugFrameMode): string {
  switch (mode) {
    case 'inventory_identify':
      return 'Inventory identify';
    case 'raw_client':
      return 'Raw client';
    case 'inventory_grid':
      return 'Grid only';
    default:
      return mode;
  }
}
