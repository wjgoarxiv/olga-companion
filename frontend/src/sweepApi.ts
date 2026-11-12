import type { SolverProgress } from './runContracts';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export interface SweepCaseStatus {
  index: number;
  path: string;
  valid: boolean;
  validation_errors: string[];
  params: Record<string, unknown>[];
  run_id: string | null;
  state: string;
  ok: boolean;
  pvt_files: string[];
  exit_code?: number | null;
  elapsed_ms?: number;
  log_tail?: string;
  error?: string;
  cancel_requested: boolean;
  solver_progress: SolverProgress;
}

export interface SweepStatus {
  sweep_id: string;
  plan_id: string;
  state: string;
  ok: boolean;
  dry_run: boolean;
  base: string;
  strategy: string;
  sweeps: string[];
  timeout_s: number;
  output_dir: string;
  cases: SweepCaseStatus[];
  case_count: number;
  counts: Readonly<Record<string, number>>;
  elapsed_ms: number;
  approval_payload: {
    sweep_id: string;
    plan_id: string;
  };
}

export interface SweepParameterOption {
  path: string;
  keyword: string;
  key: string;
}

export async function fetchSweepParameters(
  base: string,
  signal?: AbortSignal,
): Promise<SweepParameterOption[]> {
  const catalog = (await jsonOrThrow(
    await apiFetch('/api/sweep/parameters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base }),
      signal,
    }),
  )) as { parameters: SweepParameterOption[] };
  return catalog.parameters;
}

export async function sweepPreview(
  base: string,
  sweeps: string[],
  strategy = 'oat',
  maxCases = 20,
  timeoutS = 3600,
): Promise<SweepStatus> {
  return (await jsonOrThrow(
    await apiFetch('/api/sweep/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base, sweeps, strategy, max_cases: maxCases, timeout_s: timeoutS }),
    }),
  )) as SweepStatus;
}

export async function sweepExecute(sweepId: string, planId: string): Promise<SweepStatus> {
  return (await jsonOrThrow(
    await apiFetch('/api/sweep/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sweep_id: sweepId, plan_id: planId, approved: true }),
    }),
  )) as SweepStatus;
}

export async function sweepStatus(sweepId: string): Promise<SweepStatus> {
  return (await jsonOrThrow(
    await apiFetch(`/api/sweep/status/${encodeURIComponent(sweepId)}`),
  )) as SweepStatus;
}

export interface SweepSummaryCell {
  value: number | null;
  unit: string | null;
  time: number | null;
  time_unit: string | null;
  reason: string | null;
}

export interface SweepSummaryRow {
  index: number;
  params: Record<string, unknown>[];
  run_id: string | null;
  state: string;
  ok: boolean;
  tpl: string | null;
  outputs: Record<string, SweepSummaryCell>;
}

export interface SweepSummary {
  sweep_id: string;
  case_count: number;
  rows: SweepSummaryRow[];
}

export async function sweepSummary(sweepId: string): Promise<SweepSummary> {
  return (await jsonOrThrow(
    await apiFetch(`/api/sweep/summary/${encodeURIComponent(sweepId)}`),
  )) as SweepSummary;
}

export async function sweepCancel(sweepId: string): Promise<SweepStatus> {
  return (await jsonOrThrow(
    await apiFetch(`/api/sweep/cancel/${encodeURIComponent(sweepId)}`, {
      method: 'POST',
    }),
  )) as SweepStatus;
}
