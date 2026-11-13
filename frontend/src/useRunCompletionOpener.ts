import { useEffect, useRef } from 'react';
import { rescanResultInventory } from './resultInventoryCache';
import { collectCompletedRunIds, collectLaunchedRunIds, findRunCompletion, pickRunResult } from './runCompletion';
import { publishRunFinish, toRunFinishState } from './runFinishStore';
import { runStatus } from './runApi';
import { runStatusIsPollable } from './runPolling.mjs';
import { claimTaskbarPoll, releaseTaskbarPoll, rememberTaskbarTarget } from './taskbarRunFeed.mjs';
import { fetchResults } from './session';
import type { TimelineItem } from './timeline';

type RunCompletionOpener = {
  readonly timeline: readonly TimelineItem[];
  readonly sessionId: string | null;
  readonly composerText: string;
  readonly workspaceRoot: string;
  readonly activeCaseName: string | null;
  readonly preferResult: (resultId: string) => void;
  readonly openResultsView: () => void;
};

/** A completed run refreshes the Results list, selects its own output and
    opens Results — unless the composer holds text, in which case the output
    stays selected and the step bar Next action ("Open results") waits.
    Returns the announcer the Run view calls on its live completion. */
export function useRunCompletionOpener(args: RunCompletionOpener): (runId: string) => void {
  const { timeline, sessionId } = args;
  // A watched run ends many renders later; read the props as they are then.
  const latestRef = useRef(args);
  latestRef.current = args;
  const handledRunIdsRef = useRef<Set<string>>(new Set());
  const seededSessionRef = useRef<string | undefined>(undefined);
  const watchedRunIdsRef = useRef<Set<string>>(new Set());
  function announce(runId: string): void {
    const { composerText, workspaceRoot, activeCaseName, preferResult, openResultsView } = latestRef.current;
    if (!workspaceRoot || !runId || handledRunIdsRef.current.has(runId)) return;
    handledRunIdsRef.current.add(runId);
    // A chat-reported completion is a completed terminal state: publish it so
    // restored cards following the same run finish without polling again.
    publishRunFinish(runId, 'completed');
    const typing = composerText.trim() !== '';
    void (async () => {
      try {
        const inventory = await rescanResultInventory(workspaceRoot, fetchResults);
        const picked = pickRunResult(inventory.results, { runId, activeCaseName });
        if (!picked) return;
        preferResult(picked.id);
        if (!typing) openResultsView();
      } catch {
        return;
      }
    })();
  }
  // A run the chat launched is polled until it ends, so it opens even when
  // the model never patrols it. Every terminal state is published to the
  // store for the cards; only a completed run announces (opens Results).
  function watch(runId: string): void {
    if (watchedRunIdsRef.current.has(runId) || handledRunIdsRef.current.has(runId)) return;
    watchedRunIdsRef.current.add(runId);
    const owner = `opener:${runId}`;
    rememberTaskbarTarget({ kind: 'run', id: runId });
    claimTaskbarPoll(owner, { kind: 'run', id: runId });
    void (async () => {
      try {
        for (;;) {
          try {
            const status = await runStatus(runId);
            if (!runStatusIsPollable(status)) {
              const finish = toRunFinishState(status.state);
              if (finish) publishRunFinish(runId, finish);
              if (status.state === 'completed') announce(runId);
              return;
            }
          } catch {
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 3000));
        }
      } finally {
        releaseTaskbarPoll(owner);
      }
    })();
  }
  useEffect(() => {
    // A new or reopened chat replaces the timeline from its first item; seed
    // what it already holds instead of announcing it.
    const timelineKey = `${sessionId ?? ''}|${timeline[0]?.id ?? ''}`;
    if (seededSessionRef.current !== timelineKey) {
      seededSessionRef.current = timelineKey;
      for (const runId of collectCompletedRunIds(timeline)) handledRunIdsRef.current.add(runId);
      for (const runId of collectLaunchedRunIds(timeline)) watchedRunIdsRef.current.add(runId);
      return;
    }
    for (const runId of collectLaunchedRunIds(timeline)) watch(runId);
    const completion = findRunCompletion(timeline, handledRunIdsRef.current);
    if (!completion) return;
    announce(completion.runId);
  });
  return announce;
}
