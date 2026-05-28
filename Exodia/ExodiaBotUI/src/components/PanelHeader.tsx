import './PanelHeader.css';

type PanelHeaderProps = {
  title: string;
  actions?: React.ReactNode;
  minimizable?: boolean;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  /** Vertical strip mode (Log column, or stacked right-column strip). */
  strip?: 'none' | 'vertical';
};

export function PanelHeader({
  title,
  actions,
  minimizable = false,
  collapsed = false,
  onToggleCollapse,
  strip = 'none',
}: PanelHeaderProps) {
  const canCollapse = minimizable && onToggleCollapse;

  if (collapsed && strip === 'vertical') {
    return (
      <header
        className="panel-header panel-header--strip-vertical"
        onClick={onToggleCollapse}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggleCollapse?.();
          }
        }}
        title={`Restore ${title}`}
      >
        <span className="panel-header__strip-title">{title}</span>
        <button
          type="button"
          className="panel-header__collapse-btn"
          aria-label={`Restore ${title}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggleCollapse?.();
          }}
        >
          +
        </button>
      </header>
    );
  }

  return (
    <header
      className={`panel-header${collapsed ? ' panel-header--collapsed' : ''}`}
      onClick={collapsed && canCollapse ? onToggleCollapse : undefined}
      role={collapsed && canCollapse ? 'button' : undefined}
      tabIndex={collapsed && canCollapse ? 0 : undefined}
      onKeyDown={
        collapsed && canCollapse
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onToggleCollapse?.();
              }
            }
          : undefined
      }
    >
      <h2 className="panel-header__title">{title}</h2>
      <div className="panel-header__actions">
        {actions}
        {canCollapse && (
          <button
            type="button"
            className="panel-header__collapse-btn"
            aria-label={collapsed ? `Restore ${title}` : `Minimize ${title}`}
            title={collapsed ? 'Restore' : 'Minimize'}
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse?.();
            }}
          >
            {collapsed ? '+' : '−'}
          </button>
        )}
      </div>
    </header>
  );
}
