import type { RunStatus, SweepStatus } from './session';

export function runStatusIsPollable(status: Pick<RunStatus, 'state' | 'cancel_requested'>): boolean;
export function runToAdopt(
  observation: { readonly kind: string; readonly status?: Partial<Pick<RunStatus, 'run_id' | 'state' | 'cancel_requested'>> } | null | undefined,
  followedId: string | null,
  seen: Set<string>,
): string | null;
export function sweepStatusIsPollable(status: Pick<SweepStatus, 'state' | 'cases'>): boolean;
