import { createRequestEpoch } from './requestEpoch.mjs';

export {
  classifyApprovalReceipt,
  classifyApprovalResumeFailure,
  createApprovalActionGuard,
  presentToolLifecycle,
  resolveApprovalCardLifecycle,
} from './approvalActionLifecycle.mjs';

const RUNTIME_FAILURES = Object.freeze({
  network: Object.freeze({
    code: 'local_runtime_offline',
    state: 'offline',
    retryable: true,
    operatorMessage: 'Local runtime is offline',
  }),
  session: Object.freeze({
    code: 'local_session_expired',
    state: 'reconnecting',
    retryable: true,
    operatorMessage: 'Local session expired',
  }),
  http: Object.freeze({
    code: 'local_runtime_unavailable',
    state: 'offline',
    retryable: true,
    operatorMessage: 'Local runtime is unavailable',
  }),
});

export const SAFE_HYDRATION_STEPS = Object.freeze([
  Object.freeze({ key: 'health', method: 'GET', protected: false }),
  Object.freeze({ key: 'token', method: 'GET', protected: false }),
  Object.freeze({ key: 'providers', method: 'GET', protected: true }),
  Object.freeze({ key: 'workspace', method: 'GET', protected: true }),
]);

export function classifyRuntimeFailure(input) {
  switch (input.kind) {
    case 'network':
      return RUNTIME_FAILURES.network;
    case 'http':
      return input.status === 401 ? RUNTIME_FAILURES.session : RUNTIME_FAILURES.http;
    default:
      throw new TypeError('Unsupported runtime failure kind');
  }
}

export function nextRuntimeState(state, event) {
  switch (state) {
    case 'connecting':
    case 'online':
    case 'reconnecting':
    case 'offline':
      break;
    default:
      throw new TypeError('Unsupported runtime lifecycle state');
  }
  switch (event) {
    case 'hydration_succeeded':
      return 'online';
    case 'transport_failed':
    case 'retry_requested':
      return 'reconnecting';
    case 'retry_exhausted':
      return 'offline';
    default:
      throw new TypeError('Unsupported runtime lifecycle event');
  }
}

export function retryDelayMs(attempt, policy) {
  if (!Number.isSafeInteger(attempt) || attempt < 1) {
    throw new RangeError('Retry attempt must be a positive safe integer');
  }
  if (!Number.isFinite(policy.baseMs) || policy.baseMs < 0
    || !Number.isFinite(policy.maxMs) || policy.maxMs < policy.baseMs) {
    throw new RangeError('Retry policy must use a non-negative ordered range');
  }
  const exponent = Math.min(attempt - 1, 30);
  return Math.min(policy.maxMs, policy.baseMs * (2 ** exponent));
}

export function createRuntimeCommitGate() {
  const epoch = createRequestEpoch();
  return Object.freeze({
    begin() {
      return epoch.begin();
    },
    isCurrent(request) {
      return epoch.isCurrent(request);
    },
    commit(request, snapshot, onCommit) {
      if (!epoch.isCurrent(request)) return false;
      onCommit(snapshot);
      return true;
    },
    invalidate() {
      epoch.invalidate();
    },
  });
}

export function createInitialSessionIntent() {
  let status = 'pending';
  return Object.freeze({
    isPending() {
      return status === 'pending';
    },
    claim(sessionId) {
      if (status !== 'pending') return false;
      if (sessionId) {
        status = 'settled';
        return false;
      }
      status = 'attempted';
      return true;
    },
  });
}

export function createRuntimeRecovery({
  operations,
  onCommit = () => {},
  classifyFailure = () => RUNTIME_FAILURES.network,
}) {
  for (const step of SAFE_HYDRATION_STEPS) {
    if (typeof operations[step.key] !== 'function') {
      throw new TypeError(`Missing safe hydration operation: ${step.key}`);
    }
  }

  const epoch = createRequestEpoch();
  let active = null;

  function retry() {
    if (active !== null) return active;
    const request = epoch.begin();
    const pending = (async () => {
      let snapshot;
      try {
        const health = await operations.health();
        const token = await operations.token();
        const providers = await operations.providers();
        const workspace = await operations.workspace();
        snapshot = { health, token, providers, workspace };
      } catch (error) {
        if (!epoch.isCurrent(request)) return { status: 'stale' };
        let failure = RUNTIME_FAILURES.network;
        try {
          const candidate = classifyFailure(error);
          if (candidate !== null && typeof candidate === 'object') {
            const canonical = Object.values(RUNTIME_FAILURES)
              .find((known) => known.code === candidate.code);
            if (canonical !== undefined
              && candidate.state === canonical.state
              && candidate.retryable === canonical.retryable
              && candidate.operatorMessage === canonical.operatorMessage) {
              failure = canonical;
            }
          }
        } catch (_classificationError) {
          failure = RUNTIME_FAILURES.network;
        }
        return {
          status: 'failed',
          failure,
        };
      }
      if (!epoch.isCurrent(request)) return { status: 'stale' };
      onCommit(snapshot);
      return { status: 'recovered', snapshot };
    })();
    active = pending;
    void pending.then(
      () => { if (active === pending) active = null; },
      () => { if (active === pending) active = null; },
    );
    return pending;
  }

  return Object.freeze({
    retry,
    invalidate() {
      epoch.invalidate();
    },
  });
}

export function shouldScheduleRuntimeProbe({ visibility, state }) {
  if (visibility !== 'visible') return false;
  // Offline keeps probing with the bounded backoff: a late sidecar comes
  // online by itself instead of waiting for the manual retry.
  return state === 'reconnecting' || state === 'online' || state === 'offline';
}

const OFFLINE_PROBE_POLICY = Object.freeze({ baseMs: 1_000, maxMs: 5_000 });

/** Bounded offline backoff: 1 s, 2 s, 4 s, then every 5 s. */
export function offlineProbeDelayMs(attempt) {
  return retryDelayMs(attempt, OFFLINE_PROBE_POLICY);
}

/** Single-arm probe timer: arming cancels the pending wait first, so
 *  repeated failures, visibility flips and manual retries can never stack
 *  overlapping probes. */
export function createProbeTimer(clock = {
  setTimeout: (handler, ms) => globalThis.setTimeout(handler, ms),
  clearTimeout: (id) => globalThis.clearTimeout(id),
}) {
  let timer = null;
  function cancel() {
    if (timer === null) return;
    clock.clearTimeout(timer);
    timer = null;
  }
  function schedule(delayMs, task) {
    cancel();
    timer = clock.setTimeout(() => {
      timer = null;
      task();
    }, delayMs);
  }
  return Object.freeze({ schedule, cancel });
}
