import { toRunFinishState, type RunFinishState } from './runFinishStore.ts';
import { runStatusIsPollable } from './runPolling.mjs';

export type RunFinishPollStatus = {
  readonly state: string;
  readonly cancel_requested: boolean;
};

export type RunFinishPollIo = {
  readonly getFinish: (runId: string) => RunFinishState | null;
  readonly pollStatus: (runId: string) => Promise<RunFinishPollStatus>;
  readonly publishFinish: (runId: string, state: RunFinishState) => void;
};

export type RunFinishPollEvents = {
  readonly onTerminal: (finish: RunFinishState) => void;
  readonly onUnknown: (state: string) => void;
};

export type RunFinishPollOptions = {
  readonly intervalMs?: number;
  readonly maxAttempts?: number;
};

/** Bounded follow-up poll for one run's end. It stops without polling when
    the store already holds the finish, re-checks the store on every iteration
    so parallel pollers never chase the same run, publishes a terminal state it
    finds itself, reports an unrecognized end state, and gives up after the
    attempt cap. The returned stop cancels a pending wait (unmount). */
export function startRunFinishPoll(
  runId: string,
  io: RunFinishPollIo,
  events: RunFinishPollEvents,
  options?: RunFinishPollOptions,
): () => void {
  const intervalMs = options?.intervalMs ?? 3000;
  const maxAttempts = options?.maxAttempts ?? 20;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempts = 0;
  async function tick(): Promise<void> {
    if (stopped || io.getFinish(runId) !== null) return;
    attempts += 1;
    let status: RunFinishPollStatus;
    try {
      status = await io.pollStatus(runId);
    } catch {
      return;
    }
    if (stopped || io.getFinish(runId) !== null) return;
    if (!runStatusIsPollable(status)) {
      const finish = toRunFinishState(status.state);
      if (finish) {
        io.publishFinish(runId, finish);
        events.onTerminal(finish);
      } else {
        events.onUnknown(status.state);
      }
      return;
    }
    if (attempts >= maxAttempts) return;
    timer = setTimeout(() => {
      void tick();
    }, intervalMs);
  }
  void tick();
  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
