export function progressAttributes(fraction, vendorPercent) {
  return typeof fraction === 'number'
    && Number.isFinite(fraction)
    && fraction >= 0
    && fraction <= 1
    && typeof vendorPercent === 'number'
    && Number.isFinite(vendorPercent)
    && vendorPercent >= 0
    && vendorPercent <= 100
    && fraction === vendorPercent / 100
    ? { value: fraction, max: 1 }
    : { max: 1 };
}

export function effectiveSolverProgress(progress, supervisionUnknown) {
  if (!supervisionUnknown || progress.liveness !== 'supervised') {
    return { ...progress, last_known: false, last_known_phase: null };
  }
  return {
    ...progress,
    phase: 'supervision_unknown',
    liveness: 'supervision_unknown',
    last_known: true,
    last_known_phase: progress.phase,
  };
}

const ACTIVITY_LABELS = {
  connecting: 'Connecting',
  queued: 'Queued',
  waiting_model: 'Waiting',
  running: 'Running',
  finalizing: 'Finalizing',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export function presentChatActivity(input) {
  const phase = typeof input.phase === 'string' && input.phase in ACTIVITY_LABELS ? input.phase : 'running';
  const started = Number.isFinite(input.started_at_ms) ? input.started_at_ms : 0;
  const now = Number.isFinite(input.now_ms) ? input.now_ms : started;
  return {
    phase,
    label: ACTIVITY_LABELS[phase],
    elapsed_ms: Math.max(0, Math.round(now - started)),
    can_cancel: Boolean(input.cancellable) && ['connecting', 'queued', 'waiting_model', 'running'].includes(phase),
    motion: input.reduced_motion ? 'static' : 'animated',
  };
}

export function eventActivityPhase(event) {
  switch (event.type) {
    case 'open': return 'waiting_model';
    case 'phase': return event.data.phase === 'queued' ? 'queued' : 'waiting_model';
    case 'approval_required':
    case 'done': return 'finalizing';
    case 'error': return 'failed';
    default: return 'running';
  }
}

const PHASE_LABEL_KEYS = {
  connecting: 'chat.phase.connecting',
  queued: 'chat.phase.queued',
  waiting_model: 'chat.phase.waitingModel',
  running: 'chat.phase.running',
  finalizing: 'chat.phase.finalizing',
  completed: 'chat.phase.completed',
  failed: 'chat.phase.failed',
  cancelled: 'chat.phase.cancelled',
};

export function localizeActivity(activity, t) {
  const key = PHASE_LABEL_KEYS[activity.phase];
  return key ? { ...activity, label: t(key) } : activity;
}
