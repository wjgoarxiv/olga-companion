/** Update download and install go through the app's own commands (0.1.20 row 12). The page
    may only check; the native side downloads, keeps the verified bytes, and installs them
    after the same stop check the backend answers, so page code cannot install around it. */

async function core() {
  return import('@tauri-apps/api/core');
}

/** Progress events have the updater plugin's shape: Started {contentLength}, Progress {chunkLength}, Finished. */
export async function downloadNative(version, onEvent, deps) {
  const { invoke, Channel } = deps ?? await core();
  const channel = new Channel();
  channel.onmessage = onEvent;
  await invoke('download_update', { version, onEvent: channel });
}

export async function installNative(version, deps) {
  const { invoke } = deps ?? await core();
  await invoke('install_update', { version });
}

/** What a failed native call says: the shell rejects with {code, message}. A stale download
    (the version moved or nothing is held) is named, so the panel can say "check again". */
export function describeNativeError(error) {
  if (error && typeof error === 'object' && !(error instanceof Error)) {
    if (error.code === 'stale') return { stale: true, message: null };
    return { stale: false, message: typeof error.message === 'string' && error.message ? error.message : null };
  }
  if (error instanceof Error) return { stale: false, message: error.message };
  return { stale: false, message: typeof error === 'string' ? error : null };
}
