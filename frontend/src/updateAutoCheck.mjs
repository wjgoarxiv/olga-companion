// One quiet update check per launch. It only reports a newer version; download and install
// stay separate clicks in Settings → Updates, which receives the found handle so it does not
// have to check again.

export const CHECK_ON_LAUNCH_KEY = 'olga.update.checkOnLaunch';
export const LAUNCH_CHECK_DELAY_MS = 8000;

let foundUpdate = null;
const foundListeners = new Set();
const openListeners = new Set();

function setFoundUpdate(update) {
  foundUpdate = update;
  for (const listener of foundListeners) listener();
}

export function browserStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readCheckOnLaunch(storage) {
  try {
    return storage?.getItem(CHECK_ON_LAUNCH_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function writeCheckOnLaunch(storage, on) {
  try {
    storage?.setItem(CHECK_ON_LAUNCH_KEY, on ? 'on' : 'off');
  } catch {
    // A blocked storage keeps the default; the toggle still works for this launch.
  }
}

// The found handle is read without consuming it, so a repeated render sees the same handle.
// Settings → Updates clears it once it starts its own check.
export function peekFoundUpdate() {
  return foundUpdate;
}

export function clearFoundUpdate() {
  if (foundUpdate !== null) setFoundUpdate(null);
}

export function subscribeFoundUpdate(listener) {
  foundListeners.add(listener);
  return () => { foundListeners.delete(listener); };
}

// The notice asks Settings to show Updates; a Settings view that is already open hears it too.
export function requestOpenUpdates() {
  for (const listener of openListeners) listener();
}

export function subscribeOpenUpdates(listener) {
  openListeners.add(listener);
  return () => { openListeners.delete(listener); };
}

export async function runLaunchCheck({
  enabled,
  check,
  wait,
  delayMs = LAUNCH_CHECK_DELAY_MS,
  isCancelled = () => false,
  isEnabled = () => true,
}) {
  if (!enabled) return { kind: 'none' };
  try {
    await wait(delayMs);
    if (isCancelled() || !isEnabled()) return { kind: 'none' };
    const update = await check();
    if (!update) return { kind: 'none' };
    if (isCancelled()) {
      await update.close?.().catch(() => undefined);
      return { kind: 'none' };
    }
    setFoundUpdate(update);
    return { kind: 'available', version: update.version };
  } catch {
    return { kind: 'none' };
  }
}
