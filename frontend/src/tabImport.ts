import { parseStrictNumber } from './strictNumber.mjs';
/** What the read-only preview route returns for a workspace CSV/XLSX of property values. */
export interface TabImportIssue {
  readonly code: string;
  readonly row: number | null;
  readonly reason: string;
  readonly params: Readonly<Record<string, unknown>>;
}

export interface TabImportSummary {
  readonly fluid_label: string;
  readonly source: string;
  readonly sheet: string | null;
  readonly calculated: false;
  readonly pressure_points: number;
  readonly temperature_points: number;
  readonly points: number;
  readonly columns: readonly string[];
  readonly ignored_columns: readonly string[];
  readonly phase: 'TWO' | 'THREE' | null;
  readonly source_units: { readonly pressure?: string; readonly temperature?: string };
  readonly pressure_range_pa?: readonly [number, number];
  readonly temperature_range_c?: readonly [number, number];
}

export interface TabImportPreview {
  readonly ok: boolean;
  readonly issues: readonly TabImportIssue[];
  readonly issue_count: number;
  readonly warnings: readonly TabImportIssue[];
  readonly summary: TabImportSummary;
  readonly text_head: string | null;
  readonly tab_sha256: string | null;
  readonly writes_nothing: true;
}

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** Issue codes that have their own translated sentence; any other code shows the server reason. */
export const TAB_IMPORT_ISSUE_CODES = [
  'header_not_found',
  'pressure_unit_missing',
  'temperature_unit_missing',
  'pressure_unit_unknown',
  'temperature_unit_unknown',
  'duplicate_axis_column',
  'duplicate_column',
  'property_unit_mismatch',
  'required_column_missing',
  'water_fraction_required',
  'water_fraction_invalid',
  'formula_no_cached',
  'missing_value',
  'not_a_number',
  'pressure_not_positive',
  'duplicate_point',
  'grid_too_small',
  'axis_not_increasing',
  'grid_too_large',
  'missing_point',
] as const;

const KNOWN: ReadonlySet<string> = new Set(TAB_IMPORT_ISSUE_CODES);

function plain(value: unknown): string | number {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ');
  return typeof value === 'number' || typeof value === 'string' ? value : String(value ?? '');
}

/** One sentence for one issue, in the user's language, with the row when the issue has one. */
export function issueText(t: Translate, issue: TabImportIssue): string {
  if (!KNOWN.has(issue.code)) return issue.reason;
  const params: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(issue.params)) params[name] = plain(value);
  if (typeof params.axis === 'string') {
    params.axis = t(params.axis === 'pressure' ? 'tabImport.axis.pressure' : 'tabImport.axis.temperature');
  }
  if (issue.row !== null) params.row = issue.row;
  return t(`tabImport.issue.${issue.code}`, params);
}

const stemOf = (rel: string): string => {
  const name = rel.replace(/\\/g, '/').split('/').pop() ?? '';
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : dot === 0 ? '' : name;
};

/** A valid fluid label from the file name: letters, digits, _ . - only, not a bare number. */
export function suggestedLabel(rel: string): string {
  const cleaned = stemOf(rel).replace(/[^A-Za-z0-9_.-]+/g, '_').replace(/^[_.-]+|[_.-]+$/g, '').slice(0, 64);
  if (cleaned === '') return 'FLUID';
  return Number.isNaN(Number(cleaned)) ? cleaned : `FLUID_${cleaned}`.slice(0, 64);
}

/** A new .tab name beside the picked file. */
export function suggestedTabName(rel: string): string {
  const parts = rel.replace(/\\/g, '/').split('/');
  parts.pop();
  const stem = stemOf(rel) || 'table';
  return [...parts, `${stem}.tab`].join('/');
}

const TAB_FILE_NAME = /^[^\\/:*?"<>|]+(\/[^\\/:*?"<>|]+)*\.tab$/i;

/** True for a relative path made of plain names that ends in .tab. */
export function isTabFileName(text: string): boolean {
  const name = text.trim();
  return TAB_FILE_NAME.test(name) && !name.split('/').includes('..');
}

/** The total water fraction as typed, or null when it is empty or outside 0 to 1. */
export function parseFraction(text: string): number | null {
  const value = parseStrictNumber(text);
  return value !== null && value >= 0 && value <= 1 ? value : null;
}

export interface ImportRequestInput {
  readonly source: string;
  readonly tab: string;
  readonly label: string;
  readonly waterFraction: number | null;
}

/** The chat request the panel drafts; the assistant calls the import tool and the approval card writes the file. */
export function importRequest(t: Translate, input: ImportRequestInput): string {
  const water = input.waterFraction === null ? '' : t('tabImport.requestWater', { fraction: input.waterFraction });
  return t('tabImport.request', { source: input.source, tab: input.tab, label: input.label, water });
}
