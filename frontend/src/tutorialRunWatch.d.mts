import type { TaskbarObservation } from './taskbarProgress.mjs';

export function demoRunSignal(
  observation: TaskbarObservation,
  installedCaseName: string | null,
): { readonly runId: string; readonly started: boolean; readonly finished: boolean } | null;
