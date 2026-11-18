// Away notifications (D1 fallback: no new runtime dependency).
//
// A notification goes out only when the window cannot show it itself:
// the document is hidden or the window is unfocused, and the Settings
// toggle is on. Delivery fans out behind one function —
// deliverAwayNotification — so an OS-toast plugin can replace the
// taskbar-flash arm later without touching the callers.

export const AWAY_NOTIFY_KEY = 'olga-companion.notify-away.v1';

export const AWAY_KINDS = Object.freeze([
  'run-finished',
  'run-failed',
  'approval-needed',
  'chat-done',
  'update-ready',
]);

export const AWAY_COLLAPSE_WINDOW_MS = 5_000;

function isAwayKind(kind) {
  return AWAY_KINDS.includes(kind);
}

export function browserStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readAwayNotifyEnabled(storage) {
  try {
    return storage?.getItem(AWAY_NOTIFY_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function writeAwayNotifyEnabled(storage, on) {
  try {
    storage?.setItem(AWAY_NOTIFY_KEY, on ? 'on' : 'off');
  } catch {
    // A blocked storage keeps the default; the toggle still works this launch.
  }
}

export function loadAwayNotifyEnabled() {
  return readAwayNotifyEnabled(browserStorage());
}

export function saveAwayNotifyEnabled(on) {
  writeAwayNotifyEnabled(browserStorage(), on);
}

export function shouldNotifyAway({ hidden, focused, enabled }) {
  return enabled === true && (hidden === true || focused === false);
}

/** Terminal run_patrol reports not yet seen: completed and failed both notify.
 *  Restored history passes through here too, so the caller seeds it silently
 *  on the first populated timeline instead of firing for old runs. */
export function newTerminalRuns(timeline, seenRunIds) {
  const fresh = [];
  for (const item of timeline) {
    if (!item || item.kind !== 'tool' || item.name !== 'run_patrol') continue;
    const result = item.result;
    if (!result || result.terminal !== true) continue;
    const runId = result.run_id;
    if (typeof runId !== 'string' || !runId || seenRunIds.has(runId)) continue;
    seenRunIds.add(runId);
    fresh.push({ runId, state: result.state });
  }
  return fresh;
}

/** A chat-done that lands right after a run finish belongs to that run's
 *  notification, not a second toast. */
export function shouldSuppressChatDone({ lastRunNotifiedAt, now = Date.now(), windowMs = AWAY_COLLAPSE_WINDOW_MS }) {
  return typeof lastRunNotifiedAt === 'number' && now - lastRunNotifiedAt < windowMs;
}

/** Collapse same-kind events inside the window so a burst becomes one toast. */
export function createAwayCollapse({ now = () => Date.now(), windowMs = AWAY_COLLAPSE_WINDOW_MS } = {}) {
  const open = new Map();
  function push(kind) {
    if (!isAwayKind(kind)) throw new TypeError(`Unknown away-notify kind: ${String(kind)}`);
    const at = now();
    const live = open.get(kind);
    if (live && at - live.firstAt < windowMs) {
      live.count += 1;
      return { kind, count: live.count, collapsed: true };
    }
    open.set(kind, { firstAt: at, count: 1 });
    return { kind, count: 1, collapsed: false };
  }
  function clear() {
    open.clear();
  }
  return Object.freeze({ push, clear });
}

/** Best-effort taskbar flash; the toast is the guaranteed arm. */
export async function flashTaskbarDefault() {
  try {
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    await getCurrentWindow().requestUserAttention();
  } catch {
    return;
  }
}

/** The single delivery seam: toast first, taskbar flash second. */
export function createAwayNotifier({ showToast, flashTaskbar = flashTaskbarDefault } = {}) {
  if (typeof showToast !== 'function') throw new TypeError('Away delivery needs a showToast');
  return async function deliver(entry) {
    if (!entry || !isAwayKind(entry.kind)) return;
    showToast(entry);
    await flashTaskbar(entry);
  };
}
