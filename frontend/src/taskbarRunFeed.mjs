// One target for the taskbar, plus who is already polling it.
// Existing pollers claim the id they fetch. The app follower polls only
// when that id is unclaimed, so a run keeps moving after Run view closes
// without a second request while a poller is live.

import { taskbarFrameForObservation } from './taskbarProgress.mjs';

const claims = new Map();
const listeners = new Set();
// Every run and sweep observation, whatever the taskbar follows (the tutorial watches these).
const runListeners = new Set();
let target = null;
let closed = null;

function subjectOf(value) {
  if (!value || (value.kind !== 'run' && value.kind !== 'sweep')) return null;
  const id = typeof value.id === 'string' ? value.id : '';
  if (!id) return null;
  return { kind: value.kind, id };
}

function observationId(observation) {
  if (!observation || typeof observation !== 'object') return null;
  if (observation.kind === 'run') {
    const id = observation.status?.run_id;
    return typeof id === 'string' && id ? id : null;
  }
  if (observation.kind === 'sweep') {
    const id = observation.status?.sweep_id;
    return typeof id === 'string' && id ? id : null;
  }
  return null;
}

export function rememberTaskbarTarget(next) {
  const subject = subjectOf(next);
  if (!subject) return false;
  if (closed && closed.kind === subject.kind && closed.id === subject.id) return false;
  if (closed) closed = null;
  target = subject;
  return true;
}

export function rememberTaskbarTargetIfAbsent(next) {
  if (target) return false;
  return rememberTaskbarTarget(next);
}

export function getTaskbarTarget() {
  return target ? { kind: target.kind, id: target.id } : null;
}

export function clearTaskbarTargetIf(match) {
  if (!target) return;
  const subject = match ? subjectOf(match) : target;
  if (!subject) return;
  if (target.kind === subject.kind && target.id === subject.id) target = null;
}

export function claimTaskbarPoll(owner, subject) {
  const claimed = subjectOf(subject);
  if (!owner || !claimed) return;
  claims.set(owner, claimed);
}

export function releaseTaskbarPoll(owner) {
  claims.delete(owner);
}

export function taskbarTargetCovered(subject) {
  const wanted = subject === undefined ? target : subjectOf(subject);
  if (!wanted) return false;
  for (const claim of claims.values()) {
    if (claim.kind === wanted.kind && claim.id === wanted.id) return true;
  }
  return false;
}

export function publishTaskbarObservation(observation) {
  if (!observation || (observation.kind !== 'run' && observation.kind !== 'sweep')) return;
  for (const listener of [...runListeners]) {
    try {
      listener(observation);
    } catch {
      // A watcher must not fail the status fetch that reported it.
    }
  }
  const id = observationId(observation);
  if (id && closed && closed.kind === observation.kind && closed.id === id) return;
  if (target && (observation.kind !== target.kind || id !== target.id)) return;
  for (const listener of [...listeners]) {
    try {
      listener(observation);
    } catch {
      // A taskbar listener must not fail the status fetch that reported it.
    }
  }
  const frame = taskbarFrameForObservation(observation);
  if (id && (frame.status === 'none' || frame.status === 'error')) {
    closed = { kind: observation.kind, id };
    if (target && target.kind === observation.kind && target.id === id) target = null;
  }
}

export function subscribeTaskbarObservations(listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function subscribeRunObservations(listener) {
  runListeners.add(listener);
  return () => {
    runListeners.delete(listener);
  };
}

export function resetTaskbarRunFeed() {
  claims.clear();
  listeners.clear();
  runListeners.clear();
  target = null;
  closed = null;
}
