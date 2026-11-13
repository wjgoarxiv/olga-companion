import { useSyncExternalStore } from 'react';
import type { I18nKey } from '../i18n/ko.ts';
import { getCaseProblemsSnapshot, subscribeCaseProblems } from './caseProblems.ts';
import { isSuccessfulToolStatus } from '../timeline.ts';
import type { TimelineItem } from '../timeline.ts';
import { SIMULATION_STEPS } from '../simulationSteps.ts';
import { directlyValidated } from './directValidation.ts';

/** Opens the StepBar detail region (the dock guide link and the
    `olga:open-simulation-guide` palette path both dispatch this). */
export const STEPBAR_DETAIL_EVENT = 'olga:open-stepbar-detail';
export const STEPBAR_DETAIL_ID = 'stepbar-detail';
/** Fired when the ① detail's fluid-table entry is activated. W3-L3 registers
    the `create-fluid-table` command for it; until then the entry stays hidden. */
export const CREATE_FLUID_TABLE_EVENT = 'olga:create-fluid-table';

export type StepStatus = 'done' | 'current' | 'blocked' | 'upcoming';

export type StepReason = 'noTab' | 'errors' | 'noWorkspace' | 'running' | null;

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
  /** Omitted means a workspace is open, so older callers keep the no-case path. */
  readonly hasWorkspace?: boolean;
  /** Solver still running. Omitted means no live run. */
  readonly runInFlight?: boolean;
}

const STEP_IDS = ['create', 'edit', 'validate', 'run', 'analyze'] as const;

type StepSlot = { readonly status: StepStatus; readonly reason: StepReason };

/** Pure mapping. At most one step is current or blocked (you are here).
    Later steps stay upcoming until the earlier gate is actually done, so an
    edit step cannot be current while approve-and-run also reads as in progress.
    ① blocked with no workspace, current with no case, done once a case is active.
    ② done once case evidence exists. ③ blocked on a missing fluid table or
    published errors; current when a case and a table exist but nothing has
    been checked; done when evidence exists with a table and no errors.
    ④ current when that check is done and no output is open yet (reason
    `running` while a run is in flight); done once outputs exist or a result
    is open. ⑤ current once outputs exist, done once one is open. */
export function deriveStepStates(inputs: StepInputs): readonly StepState[] {
  const {
    activeCaseName, tabCount, hasRunOutputs, errorCount, hasEvidence, preferredResultId,
  } = inputs;
  const hasWorkspace = inputs.hasWorkspace !== false;
  const runInFlight = inputs.runInFlight === true;
  const active = typeof activeCaseName === 'string' && activeCaseName.trim() !== '';
  const resultOpen = preferredResultId !== null;
  const passedEdit = hasEvidence || runInFlight || hasRunOutputs || resultOpen;
  const checked = passedEdit && tabCount > 0 && errorCount === 0;

  let slots: readonly StepSlot[];
  if (!hasWorkspace) {
    slots = [
      { status: 'blocked', reason: 'noWorkspace' },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
    ];
  } else if (!active) {
    slots = [
      { status: 'current', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
    ];
  } else if (tabCount <= 0) {
    slots = [
      { status: 'done', reason: null },
      { status: passedEdit ? 'done' : 'upcoming', reason: null },
      { status: 'blocked', reason: 'noTab' },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
    ];
  } else if (errorCount > 0 && !runInFlight && !hasRunOutputs && !resultOpen) {
    slots = [
      { status: 'done', reason: null },
      { status: passedEdit ? 'done' : 'upcoming', reason: null },
      { status: 'blocked', reason: 'errors' },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
    ];
  } else if (!checked) {
    slots = [
      { status: 'done', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'current', reason: null },
      { status: 'upcoming', reason: null },
      { status: 'upcoming', reason: null },
    ];
  } else if (runInFlight && !resultOpen) {
    slots = [
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'current', reason: 'running' },
      { status: 'upcoming', reason: null },
    ];
  } else if (resultOpen) {
    slots = [
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
    ];
  } else if (hasRunOutputs) {
    slots = [
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'current', reason: null },
    ];
  } else {
    slots = [
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'done', reason: null },
      { status: 'current', reason: null },
      { status: 'upcoming', reason: null },
    ];
  }

  return STEP_IDS.map((id, index) => ({
    id,
    status: slots[index].status,
    reason: slots[index].reason,
    errorCount,
  }));
}

export type NextKind =
  | 'none'
  | 'open-workspace'
  | 'new-case'
  | 'create-fluid'
  | 'edit'
  | 'validate'
  | 'preview-run'
  | 'open-run'
  | 'open-results';

/** The one button on the bar. `none` means nothing sensible to offer
    (a missing fluid table with no create command). The label is the action
    the click performs. */
export function deriveNextAction(input: {
  readonly states: readonly StepState[];
  readonly canCreateFluid: boolean;
  readonly activeView?: string | null;
}): { readonly kind: NextKind; readonly labelKey: I18nKey | null } {
  const noTab = input.states.some((step) => step.reason === 'noTab');
  if (noTab) {
    return input.canCreateFluid
      ? { kind: 'create-fluid', labelKey: 'stepbar.next.createFluid' }
      : { kind: 'none', labelKey: null };
  }
  const focus = input.states.find((step) => step.status === 'current' || step.status === 'blocked') ?? null;
  if (focus === null) {
    return input.activeView === 'results'
      ? { kind: 'edit', labelKey: 'stepbar.next.edit' }
      : { kind: 'open-results', labelKey: 'stepbar.next.results' };
  }
  if (focus.reason === 'noWorkspace') return { kind: 'open-workspace', labelKey: 'stepbar.next.openWorkspace' };
  if (focus.reason === 'running') return { kind: 'open-run', labelKey: 'stepbar.next.openRun' };
  if (focus.reason === 'errors' || focus.id === 'validate') return { kind: 'validate', labelKey: 'stepbar.next.validate' };
  if (focus.id === 'create') return { kind: 'new-case', labelKey: 'stepbar.next.create' };
  if (focus.id === 'edit') return { kind: 'edit', labelKey: 'stepbar.next.edit' };
  if (focus.id === 'run') return { kind: 'preview-run', labelKey: 'stepbar.next.run' };
  return { kind: 'open-results', labelKey: 'stepbar.next.results' };
}

const LIVE_SOLVER = new Set(['running', 'finalizing', 'supervision_unknown']);
const LIVE_TOOL = new Set(['running', 'dispatched', 'finalizing']);

/** True while the newest run on the chat timeline has not reached a terminal patrol. */
export function timelineRunInFlight(timeline: readonly TimelineItem[]): boolean {
  let live = false;
  for (const item of timeline) {
    if (item.kind !== 'tool') continue;
    if (item.name === 'run_patrol') {
      const result = item.result;
      if (!result || typeof result !== 'object' || Array.isArray(result)) continue;
      if (result.terminal === true) live = false;
      else if (typeof result.state === 'string' && LIVE_SOLVER.has(result.state)) live = true;
    } else if (item.name === 'run_execute' && LIVE_TOOL.has(item.status)) {
      live = true;
    }
  }
  return live;
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

type ToolItem = Extract<TimelineItem, { kind: 'tool' }>;

function evidenceRecord(item: ToolItem): Record<string, unknown> | null {
  if (item.name === 'case_spec_validate' || item.name === 'case_spec_compile') {
    const normalized = item.result?.normalized;
    if (normalized && typeof normalized === 'object' && !Array.isArray(normalized)) {
      return normalized as Record<string, unknown>;
    }
    return null;
  }
  if (isCleanSourceEditPlan(item)) {
    return { source_kind: 'source', validation: item.result?.validation };
  }
  return null;
}

/** Twin of ChatView's private intake helper: the latest normalized case-spec
    evidence on the timeline, or null when the agent has validated nothing yet.
    A successful source-mode case_edit_plan with clean validation counts too.
    Kept here so the step bar never depends on chat view internals. */
export function latestCaseEvidence(timeline: readonly TimelineItem[]): Record<string, unknown> | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index];
    if (item.kind !== 'tool') continue;
    const record = evidenceRecord(item);
    if (record) return record;
  }
  return null;
}

export interface StepCaseFile {
  readonly name: string;
  readonly rel: string;
  readonly suffix: string;
}

function baseName(path: string): string {
  const slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return slash < 0 ? path : path.slice(slash + 1);
}

function stemOf(fileName: string): string {
  const base = baseName(fileName);
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(0, dot) : base;
}

function namesActiveCase(value: unknown, activeCaseName: string): boolean {
  return typeof value === 'string' && value.trim() !== '' && baseName(value) === baseName(activeCaseName);
}

/** A tool counts only when its args name this case file. A spec with no
    owner is not evidence for whichever case happens to be selected. */
function toolNamesActiveCase(item: ToolItem, activeCaseName: string): boolean {
  const args = item.args;
  if (!args) return false;
  if (item.name === 'case_edit_plan') {
    if (typeof args.source === 'string' && args.source.trim() !== '') return namesActiveCase(args.source, activeCaseName);
    return namesActiveCase(args.destination_rel, activeCaseName);
  }
  if (item.name === 'case_spec_compile' || item.name === 'case_spec_validate') {
    return namesActiveCase(args.owner_source, activeCaseName);
  }
  return false;
}

function latestEvidenceForCase(
  timeline: readonly TimelineItem[],
  activeCaseName: string,
): Record<string, unknown> | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index];
    if (item.kind !== 'tool' || !toolNamesActiveCase(item, activeCaseName)) continue;
    const record = evidenceRecord(item);
    if (record) return record;
  }
  return null;
}

function fileMatchesReference(entry: StepCaseFile, reference: string): boolean {
  return entry.name === reference
    || entry.rel === reference
    || baseName(entry.name) === baseName(reference)
    || baseName(entry.rel) === baseName(reference);
}

export interface ActiveCaseStepFacts {
  readonly tabCount: number;
  readonly hasRunOutputs: boolean;
  readonly hasEvidence: boolean;
  readonly evidence: Record<string, unknown> | null;
}

/** Outputs, validation, and (when the case names its table) the .tab check
    follow the active case. Another case's .tpl or chat card must not mark
    this one finished. Without a knowable PVTFILE the table check stays
    workspace-wide. */
export function activeCaseStepFacts(input: {
  readonly activeCaseName: string | null;
  readonly cases: readonly StepCaseFile[];
  readonly timeline: readonly TimelineItem[];
  readonly directValidations?: ReadonlyMap<string, boolean>;
}): ActiveCaseStepFacts {
  const active = typeof input.activeCaseName === 'string' && input.activeCaseName.trim() !== ''
    ? input.activeCaseName.trim()
    : null;
  const workspaceTabs = input.cases.filter((entry) => entry.suffix === '.tab').length;
  if (active === null) {
    return { tabCount: workspaceTabs, hasRunOutputs: false, hasEvidence: false, evidence: null };
  }
  const stem = stemOf(active);
  const hasRunOutputs = input.cases.some((entry) =>
    (entry.suffix === '.tpl' || entry.suffix === '.ppl')
    && (stemOf(entry.name) === stem || stemOf(entry.rel) === stem));
  const evidence = latestEvidenceForCase(input.timeline, active);
  const pvtReference = typeof evidence?.pvt_reference === 'string' ? evidence.pvt_reference.trim() : '';
  const tabCount = pvtReference === ''
    ? workspaceTabs
    : (input.cases.some((entry) => fileMatchesReference(entry, pvtReference)) ? 1 : 0);
  const direct = input.directValidations?.has(baseName(active)) === true;
  const hasEvidence = direct ? directlyValidated(input.directValidations, active) : evidence !== null;
  return { tabCount, hasRunOutputs, hasEvidence, evidence };
}

export interface StepSource {
  readonly activeCaseName: string | null;
  readonly tabCount: number;
  readonly hasRunOutputs: boolean;
  readonly hasEvidence: boolean;
  readonly timeline: readonly TimelineItem[];
  readonly preferredResultId: string | null;
  readonly hasWorkspace?: boolean;
  readonly directRunInFlight?: boolean;
}

/** Reactive step states: problem errors via the case-problem bus. Callers
    pass case-scoped table, output, and evidence facts. */
export function useStepStates(source: StepSource): readonly StepState[] {
  const problems = useSyncExternalStore(subscribeCaseProblems, getCaseProblemsSnapshot);
  const errorCount = problems.filter((problem) => problem.severity === 'error').length;
  return deriveStepStates({
    activeCaseName: source.activeCaseName,
    tabCount: source.tabCount,
    hasRunOutputs: source.hasRunOutputs,
    errorCount,
    hasEvidence: source.hasEvidence,
    preferredResultId: source.preferredResultId,
    hasWorkspace: source.hasWorkspace !== false,
    runInFlight: source.directRunInFlight === true || timelineRunInFlight(source.timeline),
  });
}
