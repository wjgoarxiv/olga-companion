import { ko } from './i18n/ko.ts';
import type { TranslateFn } from './i18n/index.ts';
import { reasonParams } from './runReason.ts';

export const PIPE_DRAFT_TOOLS = ['pipe_table_import', 'case_draft_review', 'case_draft_edit'] as const;

const COUNT_KEYS = ['flowpaths', 'pipes', 'junctions', 'boundaries', 'valves', 'sections'] as const;
const CAP_KEYS = ['nodes', 'flowpaths', 'valves', 'sections'] as const;
const NEAR_LIMIT = 0.9;
const MAX_ISSUES = 20;
const MAX_ROWS = 50;

export type DraftCountKey = (typeof COUNT_KEYS)[number];
export type DraftCapKey = (typeof CAP_KEYS)[number];

export interface DraftIssue {
  readonly row: number | null;
  readonly field: string;
  readonly reason: string;
  readonly code: string;
  readonly params: Record<string, string | number>;
}
export interface DraftCap { readonly key: DraftCapKey; readonly value: number; readonly limit: number; readonly near: boolean }
export interface DraftFlowpathRow {
  readonly label: string;
  readonly sourceName: string;
  readonly from: string;
  readonly to: string;
  readonly pipes: number;
  readonly sections: number;
}
export interface DraftStart { readonly pressureBar: number; readonly temperatureC: number; readonly stated: boolean }
export interface PipeDraftView {
  readonly ready: boolean;
  readonly draftId: string;
  readonly revision: number;
  readonly sourceName: string;
  readonly counts: Readonly<Record<DraftCountKey, number>> | null;
  readonly caps: readonly DraftCap[];
  readonly shortest: number | null;
  readonly longest: number | null;
  readonly worstRatio: number | null;
  readonly junctionWarnings: number;
  readonly start: DraftStart | null;
  readonly startWarning: { readonly highestBar: number; readonly lowestBar: number } | null;
  readonly issueCount: number;
  readonly issues: readonly DraftIssue[];
  readonly applied: readonly string[];
  readonly page: { readonly page: number; readonly pages: number; readonly rows: readonly DraftFlowpathRow[] } | null;
}

type Raw = Record<string, unknown>;

function record(value: unknown): Raw | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Raw : null;
}

function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

const PA_PER_BAR = 1e5;

function start(value: unknown): DraftStart | null {
  const item = record(value);
  const pressure = count(item?.pressure_pa);
  const temperature = item?.temperature_c;
  if (!item || pressure === null || typeof temperature !== 'number' || !Number.isFinite(temperature)) return null;
  return { pressureBar: pressure / PA_PER_BAR, temperatureC: temperature, stated: item.stated === true };
}

function startWarning(value: unknown): PipeDraftView['startWarning'] {
  const item = record(value);
  const highest = count(item?.highest_pressure_pa);
  const lowest = count(item?.lowest_pressure_pa);
  return highest === null || lowest === null ? null : { highestBar: highest / PA_PER_BAR, lowestBar: lowest / PA_PER_BAR };
}

function issues(value: unknown): DraftIssue[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, MAX_ISSUES).flatMap((entry) => {
    const item = record(entry);
    if (!item) return [];
    const row = count(item.row);
    return [{
      row,
      field: text(item.field),
      reason: text(item.reason),
      code: text(item.code),
      params: reasonParams(item.params),
    }];
  });
}

function counts(value: unknown): Record<DraftCountKey, number> | null {
  const raw = record(value);
  if (!raw) return null;
  const out = {} as Record<DraftCountKey, number>;
  for (const key of COUNT_KEYS) {
    const n = count(raw[key]);
    if (n === null) return null;
    out[key] = n;
  }
  return out;
}

function caps(value: unknown): DraftCap[] {
  const raw = record(value);
  if (!raw) return [];
  return CAP_KEYS.flatMap((key) => {
    const entry = record(raw[key]);
    const used = count(entry?.value);
    const limit = count(entry?.limit);
    if (used === null || limit === null || limit === 0) return [];
    return [{ key, value: used, limit, near: used / limit >= NEAR_LIMIT }];
  });
}

function rows(value: unknown): DraftFlowpathRow[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, MAX_ROWS).flatMap((entry) => {
    const item = record(entry);
    const label = text(item?.label);
    if (!item || !label) return [];
    return [{
      label,
      sourceName: text(item.source_name),
      from: text(item.from),
      to: text(item.to),
      pipes: count(item.pipes) ?? 0,
      sections: count(item.sections) ?? 0,
    }];
  });
}

/** The draft tool result as card data, or null when the payload is not a draft summary
 *  (so an unexpected shape falls back to the generic read-out instead of a half-empty card). */
export function presentPipeDraft(name: string, result: Raw): PipeDraftView | null {
  if (!(PIPE_DRAFT_TOOLS as readonly string[]).includes(name)) return null;
  const found = issues(result.issues);
  if (result.created === false) {
    if (found.length === 0) return null;
    return {
      ready: false, draftId: '', revision: 0, sourceName: '', counts: null, caps: [],
      shortest: null, longest: null, worstRatio: null, junctionWarnings: 0, start: null, startWarning: null,
      issueCount: count(result.issue_count) ?? found.length, issues: found, applied: [], page: null,
    };
  }
  const draftId = text(result.draft_id);
  const revision = count(result.revision);
  const total = counts(result.counts);
  if (!draftId || revision === null || total === null) return null;
  const stats = record(result.section_stats);
  const pages = count(result.pages);
  const page = count(result.page);
  return {
    ready: found.length === 0,
    draftId,
    revision,
    sourceName: text(result.source_name),
    counts: total,
    caps: caps(result.caps),
    shortest: count(stats?.shortest_section_m),
    longest: count(stats?.longest_section_m),
    worstRatio: count(stats?.worst_ratio_in_flowpaths),
    junctionWarnings: count(result.junction_warning_count) ?? 0,
    start: start(result.initial_state),
    startWarning: startWarning(result.start_warning),
    issueCount: count(result.issue_count) ?? found.length,
    issues: found,
    applied: Array.isArray(result.applied) ? result.applied.filter((item): item is string => typeof item === 'string').slice(0, 12) : [],
    page: pages !== null && page !== null && Array.isArray(result.flowpaths)
      ? { page, pages, rows: rows(result.flowpaths) }
      : null,
  };
}

function draftReasonKey(code: string): string | null {
  if (!code) return null;
  if (code.startsWith('spec.')) return 'pipeDraft.reason.spec';
  const key = `pipeDraft.reason.${code}`;
  return Object.prototype.hasOwnProperty.call(ko, key) ? key : null;
}

/** The issue text in the app's language: the coded template with its params.
 *  A template whose placeholder is absent from the params, or a code with no
 *  key yet, falls back to the carried English reason. */
export function formatDraftReason(issue: DraftIssue, t: TranslateFn): string {
  const key = draftReasonKey(issue.code);
  if (!key) return issue.reason;
  if (key === 'pipeDraft.reason.spec') {
    const prefix = `${issue.code}: `;
    const shown = issue.reason.startsWith(prefix) ? issue.reason.slice(prefix.length) : issue.reason;
    return t(key, { reason: shown });
  }
  const template = (ko as Record<string, string | undefined>)[key];
  const names = template ? [...template.matchAll(/\{(\w+)\}/g)].map((match) => match[1]) : [];
  if (names.some((name) => !(name in issue.params))) return issue.reason;
  const params: Record<string, string | number> = { ...issue.params };
  // Wire words (boundary kinds, pipe ends) ride in as English; each locale's
  // dictionary carries its own word, and an unknown word stays raw.
  for (const [name, family] of Object.entries({ kind: 'pipeDraft.kind', at: 'pipeDraft.at' })) {
    const value = params[name];
    if (typeof value !== 'string') continue;
    const wordKey = `${family}.${value}`;
    const word = t(wordKey);
    if (word !== wordKey) params[name] = word;
  }
  return t(key, params);
}

export interface DraftNetwork {
  readonly nodes: { id: string; label: string; kind: string }[];
  readonly edges: { source: string; target: string; label: string; kind: string }[];
  readonly counts: { nodes: number; flowpaths: number; edges: number };
}

/** Expand the compact draft topology (node and edge index lists) into the map's node and edge records. */
export function expandDraftNetwork(body: unknown): DraftNetwork | null {
  const raw = record(body);
  if (!raw || !Array.isArray(raw.kinds) || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) return null;
  const kinds = raw.kinds.map((kind) => (kind === 'junction' ? 'NODE' : String(kind).toUpperCase()));
  const nodes: DraftNetwork['nodes'] = [];
  for (const entry of raw.nodes) {
    if (!Array.isArray(entry) || typeof entry[0] !== 'string') return null;
    nodes.push({ id: entry[0], label: entry[0], kind: kinds[Number(entry[1])] ?? 'NODE' });
  }
  const edges: DraftNetwork['edges'] = [];
  for (const entry of raw.edges) {
    if (!Array.isArray(entry)) return null;
    const source = nodes[Number(entry[0])];
    const target = nodes[Number(entry[1])];
    if (!source || !target) return null;
    edges.push({ source: source.id, target: target.id, label: String(entry[2] ?? ''), kind: 'FLOWPATH' });
  }
  return { nodes, edges, counts: { nodes: nodes.length, flowpaths: edges.length, edges: edges.length } };
}
