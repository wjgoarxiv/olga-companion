import { useSyncExternalStore } from 'react';

/* Shared Run console feed. useRunActions publishes lifecycle entries and the
 * lifecycle tick refreshes the live snapshot; the bottom-panel console tab
 * renders them. Text is translated at the push site; the store keeps data. */

export type RunConsoleTone = 'info' | 'ok' | 'warn' | 'fail';

export interface RunConsoleEntry {
  readonly id: number;
  readonly at: number;
  readonly tone: RunConsoleTone;
  readonly text: string;
}

export interface RunConsoleSnapshot {
  readonly phase: string | null;
  readonly simTimeS: number | null;
  readonly exitCode: number | null;
  readonly state: string | null;
  readonly starting: boolean;
  readonly logTail: readonly string[];
}

const ENTRY_CAP = 200;

let nextId = 1;
let entries: readonly RunConsoleEntry[] = [];
let snapshot: RunConsoleSnapshot = {
  phase: null,
  simTimeS: null,
  exitCode: null,
  state: null,
  starting: false,
  logTail: [],
};

const listeners = new Set<() => void>();

function notify(): void {
  listeners.forEach((listener) => {
    listener();
  });
}

export function pushRunConsoleEntry(tone: RunConsoleTone, text: string): void {
  entries = [...entries.slice(-ENTRY_CAP + 1), { id: nextId++, at: Date.now(), tone, text }];
  notify();
}

export function setRunConsoleSnapshot(partial: Partial<RunConsoleSnapshot>): void {
  snapshot = { ...snapshot, ...partial };
  notify();
}

export function clearRunConsole(): void {
  entries = [];
  snapshot = { phase: null, simTimeS: null, exitCode: null, state: null, starting: false, logTail: [] };
  notify();
}

export function getRunConsoleEntries(): readonly RunConsoleEntry[] {
  return entries;
}

export function getRunConsoleSnapshot(): RunConsoleSnapshot {
  return snapshot;
}

function subscribeRunConsole(notifyChange: () => void): () => void {
  listeners.add(notifyChange);
  return () => {
    listeners.delete(notifyChange);
  };
}

export function useRunConsoleEntries(): readonly RunConsoleEntry[] {
  return useSyncExternalStore(subscribeRunConsole, getRunConsoleEntries, getRunConsoleEntries);
}

export function useRunConsoleSnapshot(): RunConsoleSnapshot {
  return useSyncExternalStore(subscribeRunConsole, getRunConsoleSnapshot, getRunConsoleSnapshot);
}
