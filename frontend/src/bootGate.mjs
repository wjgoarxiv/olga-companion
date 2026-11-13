// Boot gate: a pure state machine for the sidecar boot overlay.
//
// The app already learns the sidecar is up through useRuntimeConnection
// (health -> session token -> providers/workspace hydration in
// runtimeLifecycle.mjs). This machine models the boot sequence only — it
// performs no fetching itself, so there is no second competing health loop.
// App.tsx feeds it from the existing runtime states:
//
//   runtime 'connecting'/'reconnecting' -> event('health_ok')   (health reachable)
//   runtime 'online'                  -> event('ready_ok')    (fully up, even from failed)
//   runtime 'offline'                 -> ignored              (probes continue; only the timeout fails)
//
// Stages: starting -> connecting -> ready | failed(reason). A late online
// signal recovers even a failed gate: only the 45 s timeout fails, because
// the runtime keeps probing in the background after a refusal.

export const BOOT_TIMEOUT_MS = 45_000;
export const BOOT_POLL_BASE_MS = 250;
export const BOOT_POLL_MAX_MS = 1_000;

export const BOOT_STAGES = Object.freeze(['starting', 'connecting']);

const PENDING = Object.freeze(new Set(['starting', 'connecting']));

export function bootPollDelayMs(attempt) {
  if (!Number.isSafeInteger(attempt) || attempt < 1) {
    throw new RangeError('Boot poll attempt must be a positive safe integer');
  }
  const exponent = Math.min(attempt - 1, 30);
  return Math.min(BOOT_POLL_MAX_MS, BOOT_POLL_BASE_MS * (2 ** exponent));
}

export function createBootGate({ now = () => Date.now(), timeoutMs = BOOT_TIMEOUT_MS } = {}) {
  if (typeof now !== 'function') throw new TypeError('Boot gate needs a now() clock');
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError('Boot gate timeout must be positive');
  }
  let phase = 'starting';
  let reason = null;
  let startedAt = now();

  function event(name) {
    switch (name) {
      case 'health_ok':
        if (phase === 'starting') phase = 'connecting';
        return phase;
      case 'ready_ok':
        if (PENDING.has(phase) || phase === 'failed') {
          phase = 'ready';
          reason = null;
        }
        return phase;
      case 'transport_failed':
        return phase;
      case 'exhausted':
        if (PENDING.has(phase)) {
          phase = 'failed';
          reason = 'offline';
        }
        return phase;
      case 'fail_unavailable':
        if (PENDING.has(phase)) {
          phase = 'failed';
          reason = 'unavailable';
        }
        return phase;
      case 'retry':
        if (phase === 'failed') {
          phase = 'starting';
          reason = null;
          startedAt = now();
        }
        return phase;
      default:
        throw new TypeError(`Unsupported boot gate event: ${String(name)}`);
    }
  }

  /** Fail pending boots that ran past the timeout. True when it transitioned. */
  function checkTimeout() {
    if (!PENDING.has(phase)) return false;
    if (now() - startedAt < timeoutMs) return false;
    phase = 'failed';
    reason = 'timeout';
    return true;
  }

  return Object.freeze({
    event,
    checkTimeout,
    phase: () => phase,
    reason: () => reason,
    isReady: () => phase === 'ready',
    isFailed: () => phase === 'failed',
    isPending: () => PENDING.has(phase),
    elapsedMs: () => now() - startedAt,
  });
}
