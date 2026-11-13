// Tiny shared store for the corporate-proxy badge.
// SettingsView tells the store to refresh after each save; the status bar
// subscribes, so the "Proxy on" badge appears without a manual reload.

import { apiFetch } from './sessionTransport';
import { jsonOrThrow } from './sessionResponse';

let state = { enabled: false, ok: false };
const listeners = new Set();

function notify() {
  for (const listener of listeners) {
    try {
      listener(state);
    } catch {
      // a broken subscriber must not break the rest
    }
  }
}

export function getProxyStatus() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function refresh() {
  try {
    const body = await jsonOrThrow(await apiFetch('/api/proxy'));
    const next = { enabled: Boolean(body.enabled), ok: Boolean(body?.last_probe?.ok) };
    if (next.enabled !== state.enabled || next.ok !== state.ok) {
      state = next;
      notify();
    }
    return state;
  } catch {
    return state;
  }
}
