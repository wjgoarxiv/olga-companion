/** Validations and runs started straight from the title bar, step bar or
    Run view (not by the assistant), keyed by case file name. The step bar
    reads these so the active case's validate and run steps follow them. */

let snapshot: ReadonlyMap<string, boolean> = new Map();
const listeners = new Set<() => void>();

function key(caseName: string): string {
  const slash = Math.max(caseName.lastIndexOf('/'), caseName.lastIndexOf('\\'));
  return (slash < 0 ? caseName : caseName.slice(slash + 1)).trim();
}

export function recordDirectValidation(caseName: string, valid: boolean): void {
  const name = key(caseName);
  if (!name) return;
  const next = new Map(snapshot);
  next.set(name, valid);
  snapshot = next;
  for (const listener of [...listeners]) listener();
}

export function getDirectValidations(): ReadonlyMap<string, boolean> {
  return snapshot;
}

export function directlyValidated(validations: ReadonlyMap<string, boolean> | undefined, caseName: string): boolean {
  return validations?.get(key(caseName)) === true;
}

export function subscribeDirectValidations(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const LIVE_RUN = new Set(['queued', 'starting', 'running', 'finalizing', 'supervision_unknown']);
let runs: ReadonlyMap<string, { readonly runId: string; readonly live: boolean }> = new Map();

/** One Run-view status poll. The newest run of a case decides whether it is live. */
export function recordDirectRun(status: {
  readonly run_id?: string;
  readonly state?: string;
  readonly source?: string;
  readonly source_name?: string;
}): void {
  const name = key(status.source_name || status.source || '');
  const runId = status.run_id ?? '';
  if (!name || !runId) return;
  const live = typeof status.state === 'string' && LIVE_RUN.has(status.state);
  const previous = runs.get(name);
  if (previous && previous.runId === runId && previous.live === live) return;
  const next = new Map(runs);
  next.set(name, { runId, live });
  runs = next;
  for (const listener of [...listeners]) listener();
}

export function directRunInFlight(caseName: string): boolean {
  return runs.get(key(caseName))?.live === true;
}

export function getDirectRuns(): ReadonlyMap<string, { readonly runId: string; readonly live: boolean }> {
  return runs;
}

export function resetDirectValidations(): void {
  snapshot = new Map();
  runs = new Map();
}
