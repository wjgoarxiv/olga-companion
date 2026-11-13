import type { RunOutput, RunPreview } from './runContracts';

export interface LogHighlights {
  readonly kind: 'fault' | 'last-lines';
  readonly lines: readonly string[];
}

export function liveRunStatus<T>(status: T | null, source: 'history' | 'live'): T | null;
export function solverLogHighlights(tail: string | null | undefined, limit?: number): LogHighlights;
export function runNextAction(
  status: { readonly state: string; readonly outputs?: readonly Pick<RunOutput, 'suffix'>[] },
  supervisionUnknown?: boolean,
  t?: ((key: string) => string) | null,
): string | null;
export function runStopNotice(
  status: { readonly state: string },
  t: (key: string) => string,
): { readonly title: string; readonly detail: string; readonly action: string | null } | null;
export function approveBlockedReason(input: {
  readonly operationActive: boolean;
  readonly runReady: boolean;
  readonly usedSelectionId?: string;
  readonly preview: Pick<RunPreview, 'selection_id'> & { readonly validation?: { readonly valid: boolean } } | null;
  readonly t?: ((key: string) => string) | null;
}): string;
