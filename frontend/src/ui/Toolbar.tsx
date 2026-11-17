export function Toolbar({
  ariaLabel,
  children,
}: {
  readonly ariaLabel: string;
  readonly children: React.ReactNode;
}) {
  return (
    <div role="toolbar" aria-label={ariaLabel} className="ui-toolbar">
      {children}
    </div>
  );
}

export function ToolbarGroup({ children }: { readonly children: React.ReactNode }) {
  return <span className="ui-toolbar-group">{children}</span>;
}

export function ToolbarSeparator() {
  return <span aria-hidden="true" className="ui-toolbar-sep" />;
}
