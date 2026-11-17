export const TASKBAR_MIN_INTERVAL_MS: 1000;
export const TASKBAR_ERROR_HOLD_MS: 4000;

export type TaskbarProgressStatus = 'none' | 'normal' | 'indeterminate' | 'error';

export interface TaskbarFrame {
  readonly status: TaskbarProgressStatus;
  readonly progress?: number;
}

export interface TaskbarSolverProgress {
  readonly fraction?: number | null;
  readonly vendor_percent?: number | null;
}

export interface TaskbarRunStatus {
  readonly state?: string;
  readonly cancel_requested?: boolean;
  readonly run_id?: string;
  readonly solver_progress?: TaskbarSolverProgress | null;
}

export interface TaskbarSweepCase {
  readonly state?: string;
  readonly solver_progress?: TaskbarSolverProgress | null;
}

export interface TaskbarSweepStatus {
  readonly state?: string;
  readonly sweep_id?: string;
  readonly cases?: readonly TaskbarSweepCase[];
}

export type TaskbarObservation =
  | { readonly kind: 'run'; readonly status: TaskbarRunStatus }
  | { readonly kind: 'sweep'; readonly status: TaskbarSweepStatus }
  | { readonly kind: 'idle' };

export function knownRunPercent(progress: TaskbarSolverProgress | null | undefined): number | null;
export function sweepKnownPercent(status: TaskbarSweepStatus | null | undefined): number | null;
export function taskbarFrameForRun(status: TaskbarRunStatus | null | undefined): TaskbarFrame;
export function taskbarFrameForSweep(status: TaskbarSweepStatus | null | undefined): TaskbarFrame;
export function taskbarFrameForObservation(observation: TaskbarObservation | null | undefined): TaskbarFrame;

export interface TaskbarDriver {
  reset(): void;
  observe(frame: TaskbarFrame): void;
  tick(): void;
}

export function createTaskbarDriver(options: {
  now: () => number;
  apply: (frame: TaskbarFrame) => void;
  minIntervalMs?: number;
  errorHoldMs?: number;
}): TaskbarDriver;
