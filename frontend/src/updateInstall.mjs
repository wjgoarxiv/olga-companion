const REFUSAL_CODES = new Set(['run_active', 'unconfirmed', 'stop_failed']);

// The native stop command rejects with { code, message } when it will not stop the backend.
function refusalOf(error) {
  if (error === null || typeof error !== 'object') return null;
  const { code, message } = error;
  return typeof code === 'string' && REFUSAL_CODES.has(code) && typeof message === 'string' && message
    ? { code, message }
    : null;
}

/**
 * Stop the local backend only if the native side confirms no run is in flight, then install.
 * A refusal ends here: the installer is never called while a run could be interrupted.
 */
export async function installUpdate({ stop, install, relaunch, describe }) {
  try {
    await stop();
  } catch (error) {
    const refusal = refusalOf(error);
    return refusal
      ? { kind: 'blocked', ...refusal }
      : { kind: 'failed', message: describe(error), backendStopped: false };
  }
  try {
    await install();
    await relaunch();
    return { kind: 'installed' };
  } catch (error) {
    return { kind: 'failed', message: describe(error), backendStopped: true };
  }
}
