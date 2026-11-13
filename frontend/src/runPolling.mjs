export function runStatusIsPollable(status) {
  return status.state === 'running'
    || status.state === 'finalizing'
    || status.state === 'supervision_unknown'
    || (status.cancel_requested === true && !['completed', 'failed', 'cancelled', 'timed_out'].includes(status.state));
}

export function sweepStatusIsPollable(status) {
  return status.state === 'running'
    || status.state === 'finalizing'
    || status.state === 'supervision_unknown'
    || status.cases.some((item) => item.state === 'finalizing'
      || (item.cancel_requested === true && !['completed', 'failed', 'cancelled', 'timed_out'].includes(item.state)));
}
