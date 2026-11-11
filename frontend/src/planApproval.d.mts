export const PLAN_ACTION: string;

export type PlanStepState = 'waiting' | 'done' | 'failed' | 'uncertain' | 'not_run';

export interface PlanInputGroup {
  readonly group: string;
  readonly items: ReadonlyArray<{ readonly name: string; readonly value: string; readonly unit: string }>;
}

export interface PlanStepRow {
  readonly index: number;
  readonly kind: string;
  readonly fields: ReadonlyArray<{ readonly key: string; readonly value: string; readonly unit: string }>;
  readonly inputs: readonly PlanInputGroup[];
  readonly unknown: readonly string[];
  readonly boundTo: number | null;
  readonly state: PlanStepState;
  readonly error: string;
}

export type PlanOutcome = 'completed' | 'started' | 'stopped' | 'uncertain';

export function planStepRows(display: unknown, result: unknown): PlanStepRow[];

export function planOutcome(result: unknown): PlanOutcome | null;

export function planSettledState(result: unknown): 'completed' | 'failed';

export function planError(result: unknown): string;
