import { useCallback, useEffect, useRef, useState } from 'react';
import {
  MENUS,
  debugModeForAction,
  isDebugModeSelected,
  refreshMenuLabel,
  type MenuActionId,
  type MenuContext,
  type MenuItemDef,
  isItemInteractive,
} from '../menu/menuConfig';
import type { DebugFrameMode } from '../../shared/ipc';
import './MenuBar.css';

type MenuBarProps = {
  onAction: (actionId: MenuActionId, item: MenuItemDef) => void;
  menuContext?: MenuContext;
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onZoomFit?: () => void;
};

export function MenuBar({ onAction, menuContext, onZoomIn, onZoomOut, onZoomFit }: MenuBarProps) {
  const ctx: MenuContext = menuContext ?? {
    botRunning: false,
    chainDirty: false,
    previewLive: false,
    hasDebugFrame: false,
    streamRunning: false,
    debugMode: 'inventory_identify',
    showTemplateTracks: true,
    showInventoryTracks: true,
    hasZoomViewport: false,
    highRes: false,
    panelsVisible: { log: true, tasks: true, scripts: true, actions: true },
  };
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const barRef = useRef<HTMLElement>(null);

  const closeMenus = useCallback(() => setOpenMenuId(null), []);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (barRef.current && !barRef.current.contains(e.target as Node)) {
        closeMenus();
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [closeMenus]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === ',') {
        e.preventDefault();
        onAction('preferences', { id: 'preferences', label: 'Preferences…' });
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'q') {
        e.preventDefault();
        onAction('quit', { id: 'quit', label: 'Quit' });
      }
      if (e.key === 'F5') {
        e.preventDefault();
        onAction('refreshDebugFrame', {
          id: 'refreshDebugFrame',
          label: refreshMenuLabel(ctx),
          shortcut: 'F5',
        });
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
        e.preventDefault();
        onZoomIn?.();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '-') {
        e.preventDefault();
        onZoomOut?.();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '0') {
        e.preventDefault();
        onZoomFit?.();
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'l') {
        e.preventDefault();
        onAction('toggleLogPanel', { id: 'toggleLogPanel', label: 'Log' });
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 't') {
        e.preventDefault();
        onAction('toggleTasksPanel', { id: 'toggleTasksPanel', label: 'Bot tasks' });
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        onAction('toggleScriptsPanel', { id: 'toggleScriptsPanel', label: 'Scripts' });
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'a') {
        e.preventDefault();
        onAction('toggleActionsPanel', { id: 'toggleActionsPanel', label: 'Actions' });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onAction, ctx, onZoomIn, onZoomOut, onZoomFit]);

  const handleItemClick = (item: MenuItemDef) => {
    closeMenus();
    if (!isItemInteractive(item, ctx)) return;
    onAction(item.id, item);
  };

  const renderLabel = (item: MenuItemDef) => {
    const mode = debugModeForAction(item.id);
    if (mode && item.radioGroup === 'debugMode') {
      const selected = isDebugModeSelected(ctx.debugMode, item.id);
      return (
        <>
          <span className="menu-bar__radio">{selected ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleShowTemplateTracks') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.showTemplateTracks ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleShowInventoryTracks') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.showInventoryTracks ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleHighRes') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.highRes ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleLogPanel') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.panelsVisible.log ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleTasksPanel') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.panelsVisible.tasks ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleScriptsPanel') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.panelsVisible.scripts ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    if (item.id === 'toggleActionsPanel') {
      return (
        <>
          <span className="menu-bar__radio">{ctx.panelsVisible.actions ? '●' : '○'}</span>
          <span>{item.label}</span>
        </>
      );
    }
    return <span>{item.label}</span>;
  };

  return (
    <nav className="menu-bar" ref={barRef} role="menubar">
      {MENUS.map((menu) => (
        <div key={menu.id} className="menu-bar__group">
          <button
            type="button"
            className={`menu-bar__label${openMenuId === menu.id ? ' menu-bar__label--open' : ''}`}
            onClick={() => setOpenMenuId(openMenuId === menu.id ? null : menu.id)}
            aria-haspopup="true"
            aria-expanded={openMenuId === menu.id}
          >
            {menu.label}
          </button>
          {openMenuId === menu.id && (
            <ul className="menu-bar__dropdown" role="menu">
              {menu.items.map((item, index) => {
                const prev = index > 0 ? menu.items[index - 1] : undefined;
                const showSeparator =
                  (item.radioGroup === 'debugMode' && prev && prev.radioGroup !== 'debugMode') ||
                  (item.id === 'toggleLogPanel' && prev?.id === 'toggleHighRes');
                const enabled = isItemInteractive(item, ctx);
                return (
                  <li key={item.id} role="none">
                    {showSeparator && <div className="menu-bar__separator" role="separator" />}
                    <button
                      type="button"
                      role="menuitem"
                      className={`menu-bar__item${enabled ? '' : ' menu-bar__item--disabled'}`}
                      disabled={!enabled}
                      title={!enabled ? item.stubMessage : undefined}
                      onClick={() => handleItemClick(item)}
                    >
                      {item.id === 'refreshDebugFrame' ? refreshMenuLabel(ctx) : renderLabel(item)}
                      {item.shortcut && (
                        <span className="menu-bar__shortcut">{item.shortcut}</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </nav>
  );
}
