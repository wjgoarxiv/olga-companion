import { useEffect } from 'react';
import { fetchRunHistory, runStatus } from './runApi';
import { runStatusIsPollable } from './runPolling.mjs';
import { sweepStatus } from './sweepApi';
import { startTaskbarFollow } from './taskbarFollow.mjs';
import { applyTaskbarProgress } from './taskbarProgressWindow.mjs';
import { getTaskbarTarget, taskbarTargetCovered } from './taskbarRunFeed.mjs';
import { fetchActiveCase } from './workspaceApi';

/** Keeps the Windows taskbar progress in step with the active run or sweep
 *  from any view. Clears the bar when this mounts. */
export function useTaskbarProgress(workspaceRoot: string): void {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = startTaskbarFollow({
      apply: (frame) => {
        void applyTaskbarProgress(frame);
      },
      schedule: (ms, fn) => {
        timer = setTimeout(fn, ms);
      },
      cancelSchedule: () => {
        if (timer !== undefined) clearTimeout(timer);
        timer = undefined;
      },
      discover: async () => {
        if (!workspaceRoot || getTaskbarTarget() || taskbarTargetCovered()) return null;
        try {
          const active = await fetchActiveCase();
          if (!active.path || getTaskbarTarget()) return null;
          const history = await fetchRunHistory(active.path, 1);
          const latest = history[0];
          if (!latest || !runStatusIsPollable(latest)) return null;
          return { kind: 'run', id: latest.run_id, status: latest };
        } catch {
          return null;
        }
      },
      pollRun: async (id) => ({ kind: 'run', status: await runStatus(id) }),
      pollSweep: async (id) => ({ kind: 'sweep', status: await sweepStatus(id) }),
    });
    return () => {
      stop();
    };
  }, [workspaceRoot]);
}
