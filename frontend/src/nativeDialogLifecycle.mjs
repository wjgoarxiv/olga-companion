export function createNativeDialogLifecycle(cancel) {
  let sequence = 0;
  let active = null;
  let disposed = false;
  return {
    mount() {
      disposed = false;
    },
    begin(requestId, contextGeneration) {
      sequence += 1;
      active = { requestId, sequence, contextGeneration };
      return active;
    },
    markTerminal(handle, contextGeneration) {
      if (disposed || active !== handle) return false;
      if (handle.contextGeneration !== undefined && handle.contextGeneration !== contextGeneration) return false;
      active = null;
      return true;
    },
    cancelForContextChange(contextGeneration) {
      const request = active;
      if (!request || request.contextGeneration === undefined || request.contextGeneration === contextGeneration) return null;
      active = null;
      try {
        Promise.resolve(cancel(request.requestId, { keepalive: true })).catch(() => {});
      } catch {
        // Context invalidation is best-effort; the detached completion is rejected.
      }
      return request.requestId;
    },
    dispose() {
      if (disposed) return null;
      disposed = true;
      const request = active;
      active = null;
      if (!request) return null;
      try {
        Promise.resolve(cancel(request.requestId, { keepalive: true })).catch(() => {});
      } catch {
        // Unmount cancellation is best-effort; the late completion remains rejected.
      }
      return request.requestId;
    },
    isDisposed() { return disposed; },
  };
}
