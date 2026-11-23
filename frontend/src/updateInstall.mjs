const REFUSAL_CODES = new Set(['run_active', 'unconfirmed', 'stop_failed']);

// The native install command rejects with { code, message } when it will not stop the backend.
function refusalOf(error) {
  if (error === null || typeof error !== 'object') return null;
  const { code, message } = error;
  return typeof code === 'string' && REFUSAL_CODES.has(code) && typeof message === 'string' && message
    ? { code, message }
    : null;
}

// Only the native side knows whether it got past the stop; it says so with this code.
function failedAfterStop(error) {
  return error !== null && typeof error === 'object' && error.code === 'install_failed';
}

/**
 * One native command checks that no run is in flight, stops the backend and installs
 * (0.1.20 row 12). A refusal ends here: the installer never ran.
 */
export async function installUpdate({ apply, relaunch, describe }) {
  try {
    await apply();
  } catch (error) {
    const refusal = refusalOf(error);
    if (refusal) return { kind: 'blocked', ...refusal };
    return { kind: 'failed', message: describe(error), backendStopped: failedAfterStop(error) };
  }
  try {
    await relaunch();
    return { kind: 'installed' };
  } catch (error) {
    return { kind: 'failed', message: describe(error), backendStopped: true };
  }
}
