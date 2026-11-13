import { useEffect, useState } from 'react';
import { browserStorage, readCheckOnLaunch, runLaunchCheck } from './updateAutoCheck.mjs';

/** The version found by the one quiet check at launch, or null. */
export function useLaunchUpdateCheck() {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    void runLaunchCheck({
      enabled: readCheckOnLaunch(browserStorage()),
      isEnabled: () => readCheckOnLaunch(browserStorage()),
      wait: (ms) => new Promise((resolve) => { timer = window.setTimeout(resolve, ms); }),
      check: async () => (await import('@tauri-apps/plugin-updater')).check(),
      isCancelled: () => cancelled,
    }).then((outcome) => {
      if (!cancelled && outcome.kind === 'available') setVersion(outcome.version);
    });
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, []);
  return { version, dismiss: () => setVersion(null) };
}
