export function Panel({
  title,
  actions,
  ariaLabel,
  children,
}: {
  readonly title: string;
  readonly actions?: React.ReactNode;
  readonly ariaLabel?: string;
  readonly children: React.ReactNode;
}) {
  return (
    <section aria-label={ariaLabel ?? title} className="ui-panel">
      <div className="ui-panel-head">
        <div className="ui-panel-title">{title}</div>
        {actions && <div className="ui-panel-actions">{actions}</div>}
      </div>
      <div className="ui-panel-body">{children}</div>
    </section>
  );
}
