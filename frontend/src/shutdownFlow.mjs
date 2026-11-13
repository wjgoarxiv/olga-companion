export const SHUTDOWN_STAGES = Object.freeze(['saving', 'stopping', 'closing']);

export function stageProgress(stage) {
  const index = SHUTDOWN_STAGES.indexOf(stage);
  if (index < 0) throw new RangeError(`Unknown shutdown stage: ${String(stage)}`);
  return (index + 1) / SHUTDOWN_STAGES.length;
}

export function startPhase({ hasActiveRun }) {
  return hasActiveRun ? 'confirm' : 'saving';
}

export function createShutdownFlow({ hasActiveRun = false } = {}) {
  let phase = startPhase({ hasActiveRun });
  let reason = null;
  const start = startPhase({ hasActiveRun });

  function event(name, detail = null) {
    switch (name) {
      case 'saved':
        if (phase === 'saving') phase = 'stopping';
        return phase;
      case 'stopped':
        if (phase === 'stopping') phase = 'closing';
        return phase;
      case 'exited':
        if (phase === 'closing') phase = 'closed';
        return phase;
      case 'confirm_quit':
        if (phase === 'confirm') {
          phase = 'saving';
          reason = null;
        }
        return phase;
      case 'confirm_stay':
        if (phase === 'confirm') phase = 'idle';
        return phase;
      case 'fail':
        if (phase !== 'closed' && phase !== 'idle') {
          phase = 'failed';
          reason = typeof detail === 'string' && detail ? detail : 'shutdown_failed';
        }
        return phase;
      case 'retry':
        if (phase === 'failed') {
          phase = start;
          reason = null;
        }
        return phase;
      default:
        throw new TypeError(`Unsupported shutdown event: ${String(name)}`);
    }
  }

  return Object.freeze({
    event,
    phase: () => phase,
    reason: () => reason,
  });
}
