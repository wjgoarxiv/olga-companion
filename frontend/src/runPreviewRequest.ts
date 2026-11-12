import { useSyncExternalStore } from 'react';

/* A pending title-bar / palette / F5 preview request. The Run view is mounted
 * only when selected, so a bare event would race the mount; a session-only
 * flag survives until the Run view consumes it through the existing preview
 * path (never execution). */

let previewRequested = false;
const listeners = new Set<() => void>();

export function requestRunPreview(): void {
  previewRequested = true;
  listeners.forEach((notify) => {
    notify();
  });
}

export function consumePreviewRequest(): boolean {
  const pending = previewRequested;
  previewRequested = false;
  if (pending) {
    listeners.forEach((notify) => {
      notify();
    });
  }
  return pending;
}

export function previewRequestPending(): boolean {
  return previewRequested;
}

function subscribePreviewRequest(notify: () => void): () => void {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
}

export function usePreviewRequest(): boolean {
  return useSyncExternalStore(subscribePreviewRequest, previewRequestPending, previewRequestPending);
}
