import { LogConsole, type LogEntry } from '../components/LogConsole';
import { PanelHeader } from '../components/PanelHeader';
import './Panel.css';

type LogPanelProps = {
  entries: LogEntry[];
  onClear: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
};

export function LogPanel({ entries, onClear, collapsed = false, onToggleCollapse }: LogPanelProps) {
  return (
    <section className={`panel panel--log${collapsed ? ' panel--collapsed-strip' : ''}`}>
      <PanelHeader
        title="Log"
        minimizable
        collapsed={collapsed}
        onToggleCollapse={onToggleCollapse}
        strip={collapsed ? 'vertical' : 'none'}
      />
      {!collapsed && (
        <div className="panel__body">
          <LogConsole entries={entries} onClear={onClear} />
        </div>
      )}
    </section>
  );
}
