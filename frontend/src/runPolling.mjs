export function runStatusIsPollable(status) {
  return status.state === 'running'
    || status.state === 'finalizing'
    || status.state === 'supervision_unknown'
    || (status.cancel_requested === true && !['completed', 'failed', 'cancelled', 'timed_out'].includes(status.state));
}

/** A live run seen on the run feed that the Run view is not following yet (one reload per id). */
export function runToAdopt(observation, followedId, seen) {
  if (observation?.kind !== 'run') return null;
  const id = observation.status?.run_id;
  if (typeof id !== 'string' || id === '' || id === followedId || seen.has(id)) return null;
  if (!runStatusIsPollable(observation.status)) return null;
  seen.add(id);
  return id;
}

export function sweepStatusIsPollable(status) {
  return status.state === 'running'
    || status.state === 'finalizing'
    || status.state === 'supervision_unknown'
    || status.cases.some((item) => item.state === 'finalizing'
      || (item.cancel_requested === true && !['completed', 'failed', 'cancelled', 'timed_out'].includes(item.state)));
}
