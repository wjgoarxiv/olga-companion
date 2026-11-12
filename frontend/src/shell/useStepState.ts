import { useSyncExternalStore } from 'react';
import { getCaseProblemsSnapshot, subscribeCaseProblems } from './caseProblems.ts';
import { isSuccessfulToolStatus } from '../timeline.ts';
import type { TimelineItem } from '../timeline.ts';
import { SIMULATION_STEPS } from '../simulationSteps.ts';

/** Opens the StepBar detail region (the dock guide link and the
    `olga:open-simulation-guide` palette path both dispatch this). */
export const STEPBAR_DETAIL_EVENT = 'olga:open-stepbar-detail';
export const STEPBAR_DETAIL_ID = 'stepbar-detail';
/** Fired when the ① detail's fluid-table entry is activated. W3-L3 registers
    the `create-fluid-table` command for it; until then the entry stays hidden. */
export const CREATE_FLUID_TABLE_EVENT = 'olga:create-fluid-table';

export type StepStatus = 'done' | 'current' | 'blocked' | 'upcoming';

export type StepReason = 'noTab' | 'errors' | null;

export interface StepState {
  readonly id: (typeof SIMULATION_STEPS)[number]['id'];
  readonly status: StepStatus;
  readonly reason: StepReason;
  readonly errorCount: number;
}

export interface StepInputs {
  readonly activeCaseName: string | null;
  readonly tabCount: number;
  readonly hasRunOutputs: boolean;
  readonly errorCount: number;
  readonly hasEvidence: boolean;
  readonly preferredResultId: string | null;
}

/** Pure mapping: step statuses derive from observable app state only.
    ① done iff a case is active. ② done iff case evidence exists (the agent has
    validated/compiled it, so conditions are known and editable). ③ blocked on
    a missing fluid table or published errors, done when evidence exists with a
    table and no errors. ④ done iff run outputs exist or a completed output is
    preferred. ⑤ done iff one is open. */
export function deriveStepStates(inputs: StepInputs): readonly StepState[] {
  const { activeCaseName, tabCount, hasRunOutputs, errorCount, hasEvidence, preferredResultId } = inputs;
  const active = activeCaseName !== null;
  const step3: StepState = !active
    ? { id: 'validate', status: 'upcoming', reason: null, errorCount }
    : tabCount === 0
      ? { id: 'validate', status: 'blocked', reason: 'noTab', errorCount }
      : errorCount > 0
        ? { id: 'validate', status: 'blocked', reason: 'errors', errorCount }
        : hasEvidence
          ? { id: 'validate', status: 'done', reason: null, errorCount }
          : { id: 'validate', status: 'current', reason: null, errorCount };
  return [
    { id: 'create', status: active ? 'done' : 'current', reason: null, errorCount },
    { id: 'edit', status: !active ? 'upcoming' : hasEvidence ? 'done' : 'current', reason: null, errorCount },
    step3,
    { id: 'run', status: !active ? 'upcoming' : hasRunOutputs || preferredResultId !== null ? 'done' : 'current', reason: null, errorCount },
    {
      id: 'analyze',
      status: preferredResultId !== null ? 'done' : !hasRunOutputs ? 'upcoming' : 'current',
      reason: null,
      errorCount,
    },
  ];
}

/** A successful source-mode case_edit_plan ran the parser and the validator,
    so its clean validation counts as case evidence even though no
    case_spec_validate card exists in that chat. */
function isCleanSourceEditPlan(item: Extract<TimelineItem, { kind: 'tool' }>): boolean {
  if (item.name !== 'case_edit_plan' || !isSuccessfulToolStatus(item.status)) return false;
  const result = item.result;
  if (!result || typeof result !== 'object' || Array.isArray(result) || result.publishable !== true) return false;
  const sourceMode = result.source_kind === 'source'
    || (typeof item.args?.source === 'string' && item.args.source.length > 0);
  if (!sourceMode) return false;
  const validation = result.validation;
  return typeof validation === 'object' && validation !== null && !Array.isArray(validation)
    && (validation as Record<string, unknown>).clean === true;
}

/** Twin of ChatView's private intake helper: the latest normalized case-spec
    evidence on the timeline, or null when the agent has validated nothing yet.
    A successful source-mode case_edit_plan with clean validation counts too.
    Kept here so the step bar never depends on chat view internals. */
export function latestCaseEvidence(timeline: readonly TimelineItem[]): Record<string, unknown> | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index];
    if (item.kind !== 'tool') continue;
    if (item.name === 'case_spec_validate' || item.name === 'case_spec_compile') {
      const normalized = item.result?.normalized;
      if (normalized && typeof normalized === 'object' && !Array.isArray(normalized)) {
        return normalized as Record<string, unknown>;
      }
    } else if (isCleanSourceEditPlan(item)) {
      return { source_kind: 'source', validation: item.result?.validation };
    }
  }
  return null;
}

export interface StepSource {
  readonly activeCaseName: string | null;
  readonly tabCount: number;
  readonly hasRunOutputs: boolean;
  readonly timeline: readonly TimelineItem[];
  readonly preferredResultId: string | null;
}

/** Reactive step states: problem errors via the case-problem bus, evidence
    via the chat timeline passed in from the shell. */
export function useStepStates(source: StepSource): readonly StepState[] {
  const problems = useSyncExternalStore(subscribeCaseProblems, getCaseProblemsSnapshot);
  const errorCount = problems.filter((problem) => problem.severity === 'error').length;
  const hasEvidence = latestCaseEvidence(source.timeline) !== null;
  return deriveStepStates({
    activeCaseName: source.activeCaseName,
    tabCount: source.tabCount,
    hasRunOutputs: source.hasRunOutputs,
    errorCount,
    hasEvidence,
    preferredResultId: source.preferredResultId,
  });
}
