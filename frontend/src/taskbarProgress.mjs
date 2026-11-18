// Run state -> Windows taskbar progress. Pure: no window, no clock, no I/O.
// A known fraction is the same pair the in-app bar accepts (fraction matches
// vendor percent). Anything still going without that pair is indeterminate.

import { progressAttributes } from './progressPresentation.mjs';
import { runStatusIsPollable, sweepStatusIsPollable } from './runPolling.mjs';

export const TASKBAR_MIN_INTERVAL_MS = 1000;
export const TASKBAR_ERROR_HOLD_MS = 4000;

const STOPPED = new Set(['failed', 'cancelled', 'timed_out', 'stopped']);
const CASE_DONE = new Set(['completed', 'failed', 'cancelled', 'timed_out']);

export function knownRunPercent(progress) {
  if (!progress || typeof progress !== 'object') return null;
  const shown = progressAttributes(progress.fraction, progress.vendor_percent);
  if (typeof shown.value !== 'number' || !Number.isFinite(shown.value)) return null;
  return Math.max(0, Math.min(100, Math.round(shown.value * 100)));
}

export function sweepKnownPercent(status) {
  const cases = Array.isArray(status?.cases) ? status.cases : [];
  if (cases.length === 0) return null;
  let sum = 0;
  for (const item of cases) {
    if (!item || typeof item !== 'object') return null;
    if (CASE_DONE.has(item.state)) {
      sum += 1;
      continue;
    }
    const part = knownRunPercent(item.solver_progress);
    if (part == null) return null;
    sum += part / 100;
  }
  return Math.max(0, Math.min(100, Math.round((sum / cases.length) * 100)));
}

function runningFrame(percent) {
  if (percent == null) return { status: 'indeterminate' };
  return { status: 'normal', progress: percent };
}

function terminalFrame(state) {
  if (state === 'completed') return { status: 'none' };
  if (STOPPED.has(state)) return { status: 'error' };
  return { status: 'none' };
}

export function taskbarFrameForRun(status) {
  if (!status || typeof status !== 'object') return { status: 'none' };
  const state = typeof status.state === 'string' ? status.state : '';
  if (runStatusIsPollable({ state, cancel_requested: status.cancel_requested === true })) {
    return runningFrame(knownRunPercent(status.solver_progress));
  }
  return terminalFrame(state);
}

export function taskbarFrameForSweep(status) {
  if (!status || typeof status !== 'object') return { status: 'none' };
  const state = typeof status.state === 'string' ? status.state : '';
  const cases = Array.isArray(status.cases) ? status.cases : [];
  if (sweepStatusIsPollable({ state, cases })) {
    return runningFrame(sweepKnownPercent(status));
  }
  return terminalFrame(state);
}

export function taskbarFrameForObservation(observation) {
  if (!observation || typeof observation !== 'object') return { status: 'none' };
  if (observation.kind === 'run') return taskbarFrameForRun(observation.status);
  if (observation.kind === 'sweep') return taskbarFrameForSweep(observation.status);
  return { status: 'none' };
}

function frameKey(frame) {
  return frame.status === 'normal' ? `normal:${frame.progress}` : frame.status;
}

/** Applies frames to the taskbar. Percent changes wait out the minimum
 *  interval; a status change (including the brief error, then clear) does not. */
export function createTaskbarDriver({
  now,
  apply,
  minIntervalMs = TASKBAR_MIN_INTERVAL_MS,
  errorHoldMs = TASKBAR_ERROR_HOLD_MS,
}) {
  let last = null;
  let lastAt = -Infinity;
  let errorUntil = null;

  function emit(frame, at) {
    if (last && frameKey(last) === frameKey(frame)) return;
    last = frame;
    lastAt = at;
    apply(frame);
  }

  return {
    reset() {
      errorUntil = null;
      last = null;
      emit({ status: 'none' }, now());
    },
    observe(frame) {
      if (!frame || typeof frame.status !== 'string') return;
      const at = now();
      if (frame.status === 'error') {
        if (!last || last.status !== 'error') {
          errorUntil = at + errorHoldMs;
          emit({ status: 'error' }, at);
        }
        return;
      }
      if (errorUntil != null && at < errorUntil) {
        if (frame.status === 'none') return;
        errorUntil = null;
      }
      if (last && last.status === 'normal' && frame.status === 'normal' && at - lastAt < minIntervalMs) return;
      emit(frame, at);
    },
    tick() {
      if (errorUntil == null) return;
      const at = now();
      if (at < errorUntil) return;
      errorUntil = null;
      emit({ status: 'none' }, at);
    },
  };
}
