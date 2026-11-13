import type { TaskbarFrame, TaskbarRunStatus, TaskbarSweepStatus } from './taskbarProgress.mjs';

export interface TaskbarFollowIo {
  now?: () => number;
  apply: (frame: TaskbarFrame) => void;
  schedule: (ms: number, fn: () => void) => void;
  cancelSchedule: () => void;
  discover: () => Promise<
    | { kind: 'run'; id: string; status: TaskbarRunStatus }
    | { kind: 'sweep'; id: string; status: TaskbarSweepStatus }
    | null
  >;
  pollRun: (id: string) => Promise<{ kind: 'run'; status: TaskbarRunStatus }>;
  pollSweep: (id: string) => Promise<{ kind: 'sweep'; status: TaskbarSweepStatus }>;
  minIntervalMs?: number;
  errorHoldMs?: number;
}

export function startTaskbarFollow(io: TaskbarFollowIo): () => void;
