export type BadgeTone = 'neutral' | 'pass' | 'warn' | 'fail' | 'info';

export function Badge({
  tone = 'neutral',
  children,
}: {
  readonly tone?: BadgeTone;
  readonly children: React.ReactNode;
}) {
  return <span className={`ui-badge ui-badge-${tone}`}>{children}</span>;
}
