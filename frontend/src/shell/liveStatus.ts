import { useEffect, useSyncExternalStore } from 'react';
import { subscribeRunObservations } from '../taskbarRunFeed.mjs';
import { taskbarFrameForRun, type TaskbarObservation } from '../taskbarProgress.mjs';
import type { NextKind, StatusLineKey } from './useStepState.ts';

/** What the title bar, the step bar and the tab strip share: the one status
    line, the next action it points at, and the live run (percent, finished,
    failed). Display only: nothing here approves, sends or starts anything. */

export interface StatusLine {
  readonly key: StatusLineKey;
  readonly params: Record<string, string | number>;
}

export type TabBadgeKind = 'running' | 'newResult' | 'error';
export type TabBadgeView = 'run' | 'results';

export interface LiveStatus {
  readonly statusLine: StatusLine | null;
  readonly nextKind: NextKind | null;
  readonly runLive: boolean;
  readonly runPercent: number | null;
  /** Newest run that finished OK / failed after being seen live this session. */
  readonly completedRunId: string | null;
  readonly failedRunId: string | null;
  readonly ackedResultRunId: string | null;
  readonly ackedErrorRunId: string | null;
}

const EMPTY: LiveStatus = {
  statusLine: null, nextKind: null, runLive: false, runPercent: null,
  completedRunId: null, failedRunId: null, ackedResultRunId: null, ackedErrorRunId: null,
};
const FAILED = new Set(['failed', 'timed_out', 'stopped']);

let snapshot: LiveStatus = EMPTY;
let seenLive = new Set<string>();
const listeners = new Set<() => void>();

function commit(next: LiveStatus): void {
  snapshot = next;
  for (const listener of [...listeners]) listener();
}

export function getLiveStatus(): LiveStatus {
  return snapshot;
}

export function subscribeLiveStatus(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function resetLiveStatus(): void {
  seenLive = new Set();
  commit(EMPTY);
}

export function publishStatusLine(line: StatusLine, nextKind: NextKind | null): void {
  const current = snapshot.statusLine;
  if (
    current && current.key === line.key && snapshot.nextKind === nextKind
    && JSON.stringify(current.params) === JSON.stringify(line.params)
  ) return;
  commit({ ...snapshot, statusLine: line, nextKind });
}

/** One run status poll. Only runs seen live in this session can raise a
    "new result" or "error" badge, so a restored old record stays quiet. */
export function ingestRunObservation(observation: TaskbarObservation): void {
  if (observation.kind !== 'run') return;
  const status = observation.status;
  const runId = typeof status.run_id === 'string' ? status.run_id : '';
  const frame = taskbarFrameForRun(status);
  if (frame.status === 'normal' || frame.status === 'indeterminate') {
    if (runId) seenLive.add(runId);
    const runPercent = frame.status === 'normal' ? (frame.progress ?? null) : null;
    if (snapshot.runLive && snapshot.runPercent === runPercent) return;
    commit({ ...snapshot, runLive: true, runPercent });
    return;
  }
  const state = typeof status.state === 'string' ? status.state : '';
  const known = runId !== '' && seenLive.has(runId);
  commit({
    ...snapshot,
    runLive: false,
    runPercent: null,
    completedRunId: known && state === 'completed' ? runId : snapshot.completedRunId,
    failedRunId: known && FAILED.has(state) ? runId : snapshot.failedRunId,
  });
}

/** Opening a tab acknowledges what its badge announced. */
export function acknowledgeView(view: string): void {
  if (view === 'results' && snapshot.completedRunId !== snapshot.ackedResultRunId) {
    commit({ ...snapshot, ackedResultRunId: snapshot.completedRunId });
  } else if (view === 'run' && snapshot.failedRunId !== snapshot.ackedErrorRunId) {
    commit({ ...snapshot, ackedErrorRunId: snapshot.failedRunId });
  }
}

/** Running shows while the run is live, on any tab. A new result or an error
    shows until its tab is opened. */
export function deriveTabBadges(
  status: LiveStatus,
  view: string,
): Partial<Record<TabBadgeView, TabBadgeKind>> {
  const badges: Partial<Record<TabBadgeView, TabBadgeKind>> = {};
  if (status.runLive) badges.run = 'running';
  else if (status.failedRunId !== null && status.failedRunId !== status.ackedErrorRunId && view !== 'run') badges.run = 'error';
  if (status.completedRunId !== null && status.completedRunId !== status.ackedResultRunId && view !== 'results') badges.results = 'newResult';
  return badges;
}

export type TitleBarAction = 'validate' | 'preview' | 'run';

/** The one title-bar action to emphasise: the one the step bar points at.
    A busy run keeps Run, which carries the progress fill. */
export function titleBarPrimary(nextKind: NextKind | null | undefined, runBusy: boolean): TitleBarAction {
  if (runBusy) return 'run';
  if (nextKind === 'validate') return 'validate';
  if (nextKind === 'preview-run') return 'preview';
  return 'run';
}

type Translate = (key: StatusLineKey | (string & {}), vars?: Record<string, string | number>) => string;

export function statusLineText(t: Translate, line: StatusLine): string {
  const params = line.key === 'stepbar.line.approval'
    ? { action: t(`stepbar.approvalAction.${String(line.params.action)}`) }
    : line.params;
  return t(line.key, params);
}

export function statusLineTone(key: StatusLineKey): 'wait' | 'blocked' | 'live' | 'plain' {
  if (key === 'stepbar.line.approval') return 'wait';
  if (key === 'stepbar.line.errors' || key === 'stepbar.line.noTab') return 'blocked';
  if (key === 'stepbar.line.running' || key === 'stepbar.line.runningPct') return 'live';
  return 'plain';
}

let feedUsers = 0;
let feedStop: (() => void) | null = null;

/** Subscribes to the run feed while a component that shows it is mounted. */
export function useLiveStatus(): LiveStatus {
  useEffect(() => {
    feedUsers += 1;
    if (feedUsers === 1) feedStop = subscribeRunObservations(ingestRunObservation);
    return () => {
      feedUsers -= 1;
      if (feedUsers === 0) {
        feedStop?.();
        feedStop = null;
      }
    };
  }, []);
  return useSyncExternalStore(subscribeLiveStatus, getLiveStatus, getLiveStatus);
}
