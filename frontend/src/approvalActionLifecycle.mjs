const PRESENTATION = Object.freeze({
  'awaiting-approval': Object.freeze({ label: 'Awaiting approval', terminal: false, recoverable: false }),
  dispatched: Object.freeze({ label: 'Dispatched', terminal: false, recoverable: true }),
  running: Object.freeze({ label: 'Running', terminal: false, recoverable: true }),
  finalizing: Object.freeze({ label: 'Finalizing', terminal: false, recoverable: true }),
  completed: Object.freeze({ label: 'Completed', terminal: true, recoverable: false }),
  failed: Object.freeze({ label: 'Failed', terminal: true, recoverable: false }),
  uncertain: Object.freeze({ label: 'Outcome uncertain', terminal: false, recoverable: false }),
  cancelled: Object.freeze({ label: 'Cancelled', terminal: true, recoverable: false }),
});

export function presentToolLifecycle({ state }) {
  const presentation = PRESENTATION[state];
  if (presentation === undefined) throw new TypeError('Unsupported tool lifecycle state');
  return Object.freeze({ state, ...presentation });
}

export function resolveApprovalCardLifecycle({ lifecycle, resolved, resolution }) {
  if (lifecycle !== undefined) return lifecycle;
  if (!resolved) return 'awaiting-approval';
  return resolution === 'rejected' || resolution === 'context-expired' ? 'cancelled' : 'completed';
}

export function classifyApprovalReceipt(input) {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) return 'uncertain';
  const result = input.result;
  if (input.state === 'completed'
    && result !== null
    && typeof result === 'object'
    && !Array.isArray(result)
    && result.ok === false) return 'failed';
  switch (input.state) {
    case 'awaiting':
    case 'awaiting-approval':
    case 'pending':
      return 'awaiting-approval';
    case 'dispatched':
      return 'dispatched';
    case 'running':
      return 'running';
    case 'resume_pending':
    case 'finalizing':
      return 'finalizing';
    case 'completed':
    case 'resumed':
      return 'completed';
    case 'failed':
      return 'failed';
    case 'uncertain':
      return 'uncertain';
    case 'cancelled':
    case 'rejected':
      return 'cancelled';
    default:
      return 'uncertain';
  }
}

const RESUME_CONFLICT_CODES = Object.freeze([
  'approval_context_changed',
  'approval_rejected',
  'approval_dispatch_uncertain',
]);

export function classifyApprovalResumeFailure(error) {
  if (error !== null && typeof error === 'object' && !Array.isArray(error)) {
    if (typeof error.code === 'string' && RESUME_CONFLICT_CODES.includes(error.code)) {
      return Object.freeze({ state: 'failed', recoverable: false });
    }
    const resumeAllowed = error.resumeAllowed ?? error.resume_allowed;
    if (error.state === 'uncertain' && resumeAllowed === false) {
      return Object.freeze({ state: 'uncertain', recoverable: false });
    }
  }
  return Object.freeze({ state: 'finalizing', recoverable: true });
}

export function createApprovalActionGuard() {
  let epoch = 0;
  const dispatched = new Set();
  const active = new Set();
  const activeResume = new Map();

  function createHandle(identity, phase) {
    const controller = new AbortController();
    const handle = Object.freeze({ identity, phase, epoch, signal: controller.signal, controller });
    active.add(handle);
    return handle;
  }

  function finish(handle) {
    active.delete(handle);
    if (handle.phase === 'resume' && activeResume.get(handle.identity) === handle) {
      activeResume.delete(handle.identity);
    }
  }

  return Object.freeze({
    claimDispatch(identity) {
      if (dispatched.has(identity)) return null;
      dispatched.add(identity);
      return createHandle(identity, 'dispatch');
    },
    beginResume(identity) {
      if (activeResume.has(identity)) return null;
      const handle = createHandle(identity, 'resume');
      activeResume.set(identity, handle);
      return handle;
    },
    finish,
    finishResume: finish,
    invalidate() {
      epoch += 1;
      for (const handle of active) handle.controller.abort();
      active.clear();
      activeResume.clear();
    },
    isCurrent(handle) {
      return handle.epoch === epoch && active.has(handle) && !handle.signal.aborted;
    },
  });
}
