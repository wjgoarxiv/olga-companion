// Tauri taskbar progress. Outside the shell (tests, a plain browser) this
// is a no-op and it never throws: the in-app progress bar still works.

export async function applyTaskbarProgress(frame) {
  try {
    if (!frame || typeof frame !== 'object') return;
    const status = frame.status;
    if (status !== 'none' && status !== 'normal' && status !== 'indeterminate' && status !== 'error') return;
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    const state = { status };
    if (status === 'normal' && typeof frame.progress === 'number' && Number.isFinite(frame.progress)) {
      state.progress = Math.max(0, Math.min(100, Math.round(frame.progress)));
    }
    await getCurrentWindow().setProgressBar(state);
  } catch {
    return;
  }
}
