import { useSyncExternalStore } from 'react';

/* The single Explorer filter. The Explorer tree and the Results rail both read
 * this store, so one search box filters cases, PVT tables and outputs in the
 * sidebar and result files in the rail. Session-only on purpose: a filter is
 * transient UI state, not a preference worth persisting. */

let filter = '';
const listeners = new Set<() => void>();

export function getExplorerFilter(): string {
  return filter;
}

export function setExplorerFilter(next: string): void {
  if (next === filter) return;
  filter = next;
  listeners.forEach((notify) => {
    notify();
  });
}

function subscribeExplorerFilter(notify: () => void): () => void {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
}

function snapshotExplorerFilter(): string {
  return getExplorerFilter();
}

export function useExplorerFilter(): readonly [string, (next: string) => void] {
  const value = useSyncExternalStore(subscribeExplorerFilter, snapshotExplorerFilter, snapshotExplorerFilter);
  return [value, setExplorerFilter] as const;
}
