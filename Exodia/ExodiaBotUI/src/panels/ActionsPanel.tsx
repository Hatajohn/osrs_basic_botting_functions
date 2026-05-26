import './Panel.css';

export function ActionsPanel() {
  return (
    <section className="panel panel--actions">
      <header className="panel__header">
        <h2 className="panel__title">Actions</h2>
      </header>
      <div className="panel__body panel__placeholder panel__placeholder--compact">
        <p>Simple actions and chain runner will appear here (Phases 2–3).</p>
      </div>
    </section>
  );
}
