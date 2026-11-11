import type { ResultFile } from './resultContracts';
import { runStatusIsPollable } from './runPolling.mjs';
import type { TimelineItem } from './timeline';

export type RunCompletion = {
  readonly runId: string;
};

function patrolResult(item: TimelineItem): Record<string, unknown> | null {
  if (item.kind !== 'tool' || item.name !== 'run_patrol') return null;
  const result = item.result;
  if (!result || typeof result !== 'object' || Array.isArray(result)) return null;
  return result as Record<string, unknown>;
}

/** Newest chat-reported run that reached a completed terminal state and has
    not been handled yet. Failed and bounded (non-terminal) patrol reports
    never count: a failed run must leave the chat diagnosis in front. */
export function findRunCompletion(
  timeline: readonly TimelineItem[],
  handledRunIds: ReadonlySet<string>,
): RunCompletion | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const result = patrolResult(timeline[index] as TimelineItem);
    if (!result || result.terminal !== true || result.state !== 'completed') continue;
    const runId = result.run_id;
    if (typeof runId !== 'string' || !runId || handledRunIds.has(runId)) continue;
    return { runId };
  }
  return null;
}

/** Every completed run already present in a timeline. A chat restored on
    launch or reopened from history is seeded with these so it never jumps. */
export function collectCompletedRunIds(timeline: readonly TimelineItem[]): Set<string> {
  const ids = new Set<string>();
  for (const item of timeline) {
    const result = patrolResult(item);
    if (result && result.terminal === true && result.state === 'completed'
      && typeof result.run_id === 'string' && result.run_id) ids.add(result.run_id);
  }
  return ids;
}

function launchedRunId(result: unknown): string | null {
  if (!result || typeof result !== 'object' || Array.isArray(result)) return null;
  const runId = (result as Record<string, unknown>).run_id;
  return typeof runId === 'string' && runId ? runId : null;
}

/** Runs the chat started, through run_execute directly or as an action_plan
    step. The model may never patrol them, so the shell watches these itself. */
export function collectLaunchedRunIds(timeline: readonly TimelineItem[]): Set<string> {
  const ids = new Set<string>();
  for (const item of timeline) {
    if (item.kind !== 'tool' || item.status === 'failed') continue;
    if (item.name === 'run_execute') {
      const runId = launchedRunId(item.result);
      if (runId) ids.add(runId);
    } else if (item.name === 'action_plan' && Array.isArray(item.result?.steps)) {
      for (const step of item.result.steps as unknown[]) {
        if (step && typeof step === 'object' && (step as Record<string, unknown>).kind === 'run_execute') {
          const runId = launchedRunId((step as Record<string, unknown>).result);
          if (runId) ids.add(runId);
        }
      }
    }
  }
  return ids;
}

export function pickRunResult(
  results: readonly ResultFile[],
  options: { readonly runId: string | null; readonly activeCaseName: string | null },
): ResultFile | null {
  let runMatch: ResultFile | null = null;
  let caseMatch: ResultFile | null = null;
  for (const result of results) {
    if (options.runId && result.run_id === options.runId
      && (!runMatch || result.modified_ns > runMatch.modified_ns)) {
      runMatch = result;
    }
    if (options.activeCaseName && result.source_name === options.activeCaseName
      && (!caseMatch || result.modified_ns > caseMatch.modified_ns)) {
      caseMatch = result;
    }
  }
  return runMatch ?? caseMatch;
}

type RunTransition = {
  readonly run_id: string;
  readonly state: string;
  readonly cancel_requested?: boolean;
};

/** The Run view announces a completion only on the live pollable-to-completed
    transition of one run. A completed history restored on open stays silent,
    and failed terminals never announce. */
export function shouldAnnounceRunCompletion(
  previous: RunTransition | null,
  next: RunTransition,
): string | null {
  if (!previous || previous.run_id !== next.run_id) return null;
  if (previous.state === next.state) return null;
  if (next.state !== 'completed') return null;
  if (runStatusIsPollable({ state: next.state, cancel_requested: next.cancel_requested ?? false })) return null;
  return next.run_id;
}
