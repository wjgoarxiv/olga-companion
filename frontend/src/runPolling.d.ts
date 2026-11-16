import type { RunStatus, SweepStatus } from './session';

export function runStatusIsPollable(status: Pick<RunStatus, 'state' | 'cancel_requested'>): boolean;
export function sweepStatusIsPollable(status: Pick<SweepStatus, 'state' | 'cases'>): boolean;
