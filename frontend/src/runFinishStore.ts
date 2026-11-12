import { useCallback, useSyncExternalStore } from 'react';

export type RunFinishState = 'completed' | 'failed' | 'cancelled' | 'timed_out';

function isRunFinishState(value: unknown): value is RunFinishState {
  return value === 'completed' || value === 'failed' || value === 'cancelled' || value === 'timed_out';
}

const finishes = new Map<string, RunFinishState>();
const listeners = new Map<string, Set<() => void>>();

/** The latest terminal state reported for a run, or null when it has not finished. */
export function getRunFinish(runId: string): RunFinishState | null {
  return finishes.get(runId) ?? null;
}

/** Record a run's terminal state and wake its subscribed cards. Non-terminal
    states are ignored so a stale poll can never mark a finished run as running.
    The first terminal report wins: a run ends once, so a later report for the
    same run is stale by definition. */
export function publishRunFinish(runId: string, state: RunFinishState): void {
  if (!runId || !isRunFinishState(state)) return;
  if (finishes.has(runId)) return;
  finishes.set(runId, state);
  for (const listener of listeners.get(runId) ?? []) listener();
}

/** The store's view of a runner state: its terminal states, else null, so the
    opener and the cards publish and read the same endings. */
export function toRunFinishState(state: string): RunFinishState | null {
  return isRunFinishState(state) ? state : null;
}

export function subscribeRunFinish(runId: string, listener: () => void): () => void {
  let set = listeners.get(runId);
  if (!set) {
    set = new Set();
    listeners.set(runId, set);
  }
  set.add(listener);
  return () => {
    const live = listeners.get(runId);
    if (!live) return;
    live.delete(listener);
    if (live.size === 0) listeners.delete(runId);
  };
}

/** A card's view of its run's end: the terminal state once published, else null. */
export function useRunFinish(runId: string | null): RunFinishState | null {
  const subscribe = useCallback(
    (notify: () => void): (() => void) => (runId ? subscribeRunFinish(runId, notify) : () => undefined),
    [runId],
  );
  return useSyncExternalStore(
    subscribe,
    () => (runId ? getRunFinish(runId) : null),
    () => (runId ? getRunFinish(runId) : null),
  );
}

/** Test-only reset between cases. */
export function clearRunFinishStore(): void {
  const pending = [...listeners.values()].flatMap((set) => [...set]);
  finishes.clear();
  listeners.clear();
  for (const listener of pending) listener();
}
