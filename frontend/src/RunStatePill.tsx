/* The run tab's single status source: one shared pill rendered by the
 * single-case and sweep heads. Runtime/engine state lives in the status bar. */

export function RunStatePill({ statusLabel, statusClass }: {
  readonly statusLabel: string;
  readonly statusClass: string;
}) {
  return (
    <strong className={`run-state ${statusClass}`}>{statusLabel}</strong>
  );
}
