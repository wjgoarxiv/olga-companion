import type { KeywordCoverage } from './runContracts';
import type { CaseEditRow } from './caseEditModel.mjs';
import { apiFetch } from './sessionTransport';

export type CaseEditRows = {
  readonly source: string;
  readonly source_hash: string;
  readonly context_generation: number;
  readonly marked: boolean;
  readonly rows: readonly CaseEditRow[];
  /** `not_exact_compile`: made by the app and changed by hand since, so no typed edit applies. */
  readonly reason?: string;
  /** Every keyword.key of the case: changeable in this table, only in a sweep, or not here. */
  readonly coverage?: KeywordCoverage;
};

export type CaseEditPlan = {
  readonly transaction_id: string;
  readonly source_hash: string;
  readonly compiled_hash?: string;
  readonly context_generation: number;
  readonly destination_rel: string;
  readonly publishable: boolean;
  readonly semantic_diff?: readonly { path: string; before: string; after: string }[];
  readonly text_diff?: readonly string[];
  readonly diff_truncated?: boolean;
  readonly validation?: { clean: boolean; diagnostics: readonly string[] };
  readonly errors?: readonly { code: string; message: string; evidence: string }[];
};

export type CaseEditReceipt = { readonly destination_rel: string; readonly published_hash: string };

/** A refusal or a conflict the server named; `code` is `stale_source`, `stale_context` or `refused`. */
export class CaseEditError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'CaseEditError';
    this.code = code;
  }
}

async function json<T>(response: Response): Promise<T> {
  const body: unknown = await response.json().catch(() => ({}));
  if (response.ok) return body as T;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    const record = detail as { code?: unknown; message?: unknown };
    throw new CaseEditError(String(record.code ?? 'refused'), String(record.message ?? '').slice(0, 512));
  }
  if (Array.isArray(detail)) {
    throw new CaseEditError('refused', detail.map((entry) => String((entry as { msg?: unknown }).msg ?? '')).join('; ').slice(0, 512));
  }
  throw new CaseEditError('refused', typeof detail === 'string' ? detail.slice(0, 512) : `HTTP ${response.status}`);
}

export async function fetchCaseEditRows(rel: string): Promise<CaseEditRows> {
  return json<CaseEditRows>(await apiFetch(`/api/case-edit/rows?rel=${encodeURIComponent(rel)}`));
}

/** Review the changed cells; the server compiles and validates a copy and writes no case file. */
export async function planCaseEdit(rows: CaseEditRows, operations: readonly Record<string, unknown>[]): Promise<CaseEditPlan> {
  return json<CaseEditPlan>(await apiFetch('/api/case-edit/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source: rows.source,
      source_hash: rows.source_hash,
      context_generation: rows.context_generation,
      operations,
    }),
  }));
}

/** Save the reviewed copy. Only called from the explicit Approve click. */
export async function publishCaseEdit(plan: CaseEditPlan): Promise<CaseEditReceipt> {
  return json<CaseEditReceipt>(await apiFetch('/api/case-edit/publish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transaction_id: plan.transaction_id,
      source_hash: plan.source_hash,
      compiled_hash: plan.compiled_hash,
      destination_rel: plan.destination_rel,
      context_generation: plan.context_generation,
      approved: true,
    }),
  }));
}

export type CaseDiffRow = {
  readonly component: string | null;
  readonly keyword: string;
  readonly label: string;
  readonly key?: string;
  readonly before?: string | null;
  readonly after?: string | null;
};

export type CaseDiff = {
  readonly a: string;
  readonly b: string;
  readonly same: boolean;
  readonly changed: readonly CaseDiffRow[];
  readonly removed: readonly CaseDiffRow[];
  readonly added: readonly CaseDiffRow[];
  readonly truncated: boolean;
};

/** Keyword-level differences between two workspace cases; nothing is written. */
export async function fetchCaseDiff(a: string, b: string): Promise<CaseDiff> {
  return json<CaseDiff>(await apiFetch(`/api/case-diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`));
}
