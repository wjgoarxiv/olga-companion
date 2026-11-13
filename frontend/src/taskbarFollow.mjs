// App-level follower. Clears the bar on start. While a poller claims the
// active id, it only renders observations that poller already fetched.
// When nobody claims it (Run view closed, chat not watching), it polls.

import { createTaskbarDriver, taskbarFrameForObservation } from './taskbarProgress.mjs';
import {
  getTaskbarTarget,
  publishTaskbarObservation,
  rememberTaskbarTarget,
  subscribeTaskbarObservations,
  taskbarTargetCovered,
} from './taskbarRunFeed.mjs';

const IDLE_MS = 1000;
const POLL_MS = 1500;

export function startTaskbarFollow(io) {
  const driver = createTaskbarDriver({
    now: io.now ?? (() => Date.now()),
    apply: io.apply,
    minIntervalMs: io.minIntervalMs,
    errorHoldMs: io.errorHoldMs,
  });
  let stopped = false;
  let discovered = false;
  driver.reset();
  const unsubscribe = subscribeTaskbarObservations((observation) => {
    if (!stopped) driver.observe(taskbarFrameForObservation(observation));
  });

  async function tick() {
    if (stopped) return;
    driver.tick();
    let delay = IDLE_MS;
    if (!taskbarTargetCovered(getTaskbarTarget())) {
      let skipPoll = false;
      if (!getTaskbarTarget() && !discovered) {
        discovered = true;
        try {
          const found = await io.discover();
          if (stopped) return;
          if (found && !getTaskbarTarget() && !taskbarTargetCovered(found) && rememberTaskbarTarget(found)) {
            publishTaskbarObservation({ kind: found.kind, status: found.status });
            // History already carried this snapshot. Wait until the next tick to poll.
            skipPoll = true;
          }
        } catch {
          // Discovery is one shot per mount. A miss leaves the bar clear.
        }
      }
      const live = getTaskbarTarget();
      if (!stopped && !skipPoll && live && !taskbarTargetCovered(live)) {
        delay = POLL_MS;
        try {
          const observation = live.kind === 'sweep' ? await io.pollSweep(live.id) : await io.pollRun(live.id);
          if (!stopped) publishTaskbarObservation(observation);
        } catch {
          // Keep the target. The next tick tries the same id.
        }
      }
    }
    if (!stopped) io.schedule(delay, () => { void tick(); });
  }

  void tick();
  return function stop() {
    stopped = true;
    unsubscribe();
    io.cancelSchedule();
  };
}
