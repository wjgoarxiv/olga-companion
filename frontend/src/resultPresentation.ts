import type * as session from './session';
import type { I18nKey } from './i18n/ko.ts';
import { ko } from './i18n/ko.ts';
import { en } from './i18n/en.ts';
import { DEFAULT_SIGNIFICANT_FIGURES, figuresForSpan, formatSignificant, type SignificantFigures } from './significantFigures.mjs';

export function historicalResultLabel(runId: string): string {
  return `Historical · Run ${runId} · proven` + 'ance unavailable';
}

/** Plain-language names for the OLGA output mnemonics a beginner meets first. */
const PLAIN_VARIABLE_NAMES: Readonly<Record<string, string>> = {
  PT: '압력',
  TM: '온도',
  HOL: '액체 홀드업',
  GT: '총 질량 유량',
  QT: '총 체적 유량',
  QLT: '총 액체 체적 유량',
};

const PLAIN_VARIABLE_NAMES_EN: Readonly<Record<string, string>> = {
  PT: 'pressure',
  TM: 'temperature',
  HOL: 'liquid holdup',
  GT: 'total mass flow rate',
  QT: 'total volumetric flow rate',
  QLT: 'total liquid volumetric flow rate',
};

export function plainVariableName(variable: string, locale: 'ko' | 'en' = 'ko'): string | null {
  const table = locale === 'en' ? PLAIN_VARIABLE_NAMES_EN : PLAIN_VARIABLE_NAMES;
  return table[variable.trim().toUpperCase()] ?? null;
}

export function receiptBacked(result: session.ResultFile): boolean {
  return result.lineage_status === 'receipt_output';
}

export function resultStatusLabel(result: session.ResultFile): 'Completed' | 'Failed' | 'Partial' {
  if (result.run_state === 'completed' && result.run_ok === true) return 'Completed';
  if (result.run_ok === false || result.run_state === 'failed' || result.run_state === 'timed_out' || result.run_state === 'cancelled') return 'Failed';
  return 'Partial';
}

/** Display-side dictionary key for the status word; the English word above
 *  stays as the search index so inventory filtering is locale-independent. */
export function resultStatusKey(result: session.ResultFile): I18nKey {
  const status = resultStatusLabel(result);
  if (status === 'Completed') return 'results.statusCompleted';
  if (status === 'Failed') return 'results.statusFailed';
  return 'results.statusPartial';
}

export function resultContextLabel(result: session.ResultFile): string {
  if (result.origin === 'run') {
    const runId = result.run_id || result.rel.split('/')[0] || 'unknown';
    if (result.lineage_status === 'receipt_changed') return `Run ${runId} · changed after the run · not verified`;
    return historicalResultLabel(runId);
  }
  return `Workspace package result · ${result.rel}`;
}

export function modifiedLabel(modifiedNs: number, locale: 'ko' | 'en' = 'ko'): string {
  const modified = new Date(modifiedNs / 1_000_000);
  return Number.isNaN(modified.getTime())
    ? (locale === 'en' ? en : ko)['results.timeUnavailable']
    : modified.toLocaleString(locale === 'en' ? 'en-US' : 'ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

export function resultRevisionKey(result: session.ResultFile): string {
  return `${result.id}:${result.modified_ns}:${result.size}:${result.output_sha256 ?? ''}`;
}

/** Newest output of the active case for auto-select on open. Null keeps the
 *  operator's choice (or the empty state) untouched. */
export function pickAutoSelectResult(
  results: readonly session.ResultFile[],
  activeCaseName: string | null,
  options?: { readonly selectedId?: string | null; readonly preferredId?: string | null },
): session.ResultFile | null {
  if (options?.selectedId || options?.preferredId || !activeCaseName) return null;
  let newest: session.ResultFile | null = null;
  for (const result of results) {
    if (result.source_name !== activeCaseName) continue;
    if (!newest || result.modified_ns > newest.modified_ns) newest = result;
  }
  return newest;
}

export function metric(value: number, significantFigures: number = DEFAULT_SIGNIFICANT_FIGURES): string {
  return formatSignificant(value, significantFigures);
}

/** The figures a series table needs: the chosen setting, raised so the
    series' own min-max span stays visible (see figuresForSpan). */
export function seriesFigures(receipt: unknown, significantFigures: SignificantFigures = DEFAULT_SIGNIFICANT_FIGURES): number {
  if (!isRecord(receipt)) return significantFigures;
  const analysis = isRecord(receipt.analysis) ? receipt.analysis : {};
  let low = Number(analysis.minimum);
  let high = Number(analysis.maximum);
  if (!Number.isFinite(low) || !Number.isFinite(high)) {
    const rows = Array.isArray(receipt.rows) ? receipt.rows.filter(isSeriesRow) : [];
    if (!rows.length) return significantFigures;
    low = Infinity;
    high = -Infinity;
    for (const row of rows) {
      if (row.value < low) low = row.value;
      if (row.value > high) high = row.value;
    }
  }
  return figuresForSpan(low, high, significantFigures);
}

export function filterResultVariables(
  variables: readonly session.ResultVar[],
  filter: string,
  limit: number = 80,
): readonly session.ResultVar[] {
  const query = filter.toLowerCase();
  const matched = variables
    .filter((variable) => variable.variable.toLowerCase().includes(query) || (variable.position || '').toLowerCase().includes(query));
  return Number.isFinite(limit) && limit >= 0 ? matched.slice(0, Math.floor(limit)) : matched;
}

export function filterResultFiles(results: readonly session.ResultFile[], filter: string): readonly session.ResultFile[] {
  const tokens = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return results;
  return results.filter((result) => {
    const searchable = [
      result.name,
      result.rel,
      result.run_id ?? '',
      result.origin,
      resultStatusLabel(result),
      resultContextLabel(result),
    ].join(' ').toLowerCase();
    return tokens.every((token) => searchable.includes(token));
  });
}

export type SeriesRow = { readonly time: number; readonly value: number };

export type SeriesTablePresentation = {
  readonly caption: string;
  readonly time_header: string;
  readonly value_header: string;
  readonly rows: readonly SeriesRow[];
  readonly row_summary: string;
  readonly analysis_summary?: string;
  readonly truncated: boolean;
};

/** Raw time/value units behind a series receipt, for display-only formatting. */
export function seriesTableUnits(receipt: unknown): { readonly time: string; readonly value: string } {
  if (!isRecord(receipt)) return { time: '', value: '' };
  const units = isRecord(receipt.units) ? receipt.units : {};
  return {
    time: typeof units.time === 'string' ? units.time : '',
    value: typeof units.value === 'string' ? units.value : '',
  };
}

export type ArtifactAction =
  | { readonly kind: 'download'; readonly artifact_id: string }
  | { readonly kind: 'open-results'; readonly artifact_id: string }
  | { readonly kind: 'save-as'; readonly artifact_id: string };

type ArtifactReceiptView = {
  readonly artifact_id: string;
  readonly kind: string;
  readonly mime: string;
  readonly suggested_filename: string;
  readonly sha256: string;
  readonly size?: number;
  readonly size_bytes?: number;
  readonly lineage?: Record<string, unknown>;
  readonly result_id?: string;
  readonly workspace_generation?: number;
  readonly actions?: readonly string[];
};

export type ArtifactPresentation = {
  readonly receipt: ArtifactReceiptView;
  readonly actions: readonly ArtifactAction[];
  readonly read_only?: true;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isSeriesRow(value: unknown): value is SeriesRow {
  return isRecord(value) && Number.isFinite(value.time) && Number.isFinite(value.value);
}

export type PresentationText = (key: I18nKey, vars?: Record<string, string | number>) => string;

export function presentSeriesTable(
  receipt: unknown,
  significantFigures: SignificantFigures = DEFAULT_SIGNIFICANT_FIGURES,
  t: PresentationText | null = null,
): SeriesTablePresentation | null {
  if (!isRecord(receipt) || typeof receipt.variable !== 'string' || !Array.isArray(receipt.rows)) return null;
  const rows = receipt.rows.filter(isSeriesRow).slice(0, 500);
  const returnedRows = typeof receipt.returned_rows === 'number' ? receipt.returned_rows : rows.length;
  const totalRows = typeof receipt.total_rows === 'number' ? receipt.total_rows : returnedRows;
  const units = isRecord(receipt.units) ? receipt.units : {};
  const timeUnit = typeof units.time === 'string' && units.time ? ` (${units.time})` : '';
  const valueUnit = typeof units.value === 'string' && units.value ? ` (${units.value})` : '';
  const position = typeof receipt.position === 'string' && receipt.position ? ` at ${receipt.position}` : '';
  const strategy = typeof receipt.truncation === 'string' ? receipt.truncation : 'bounded';
  const uiBounded = rows.length < returnedRows;
  const truncated = receipt.truncated === true || returnedRows < totalRows || uiBounded;
  const visibleRows = uiBounded ? rows.length : returnedRows;
  const sampleStrategy = uiBounded ? 'UI-bounded' : strategy;
  const analysis = isRecord(receipt.analysis) ? receipt.analysis : {};
  const hasAnalysis = Number.isFinite(analysis.minimum)
    && Number.isFinite(analysis.maximum)
    && Number.isFinite(analysis.mean);
  const visible = visibleRows.toLocaleString('en-US');
  const total = totalRows.toLocaleString('en-US');
  const rowSummary = t?.('series.rowSummary', { visible, total }) ?? `${visible} of ${total} rows`;
  const rowSample = truncated
    ? t?.('series.rowSample', { strategy: sampleStrategy }) ?? ` · ${sampleStrategy} sample`
    : '';
  const figures = seriesFigures(receipt, significantFigures);
  const minimum = metric(Number(analysis.minimum), figures);
  const maximum = metric(Number(analysis.maximum), figures);
  const mean = metric(Number(analysis.mean), figures);
  const analysisSummary = t?.('series.analysisSummary', { min: minimum, max: maximum, mean }) ?? `Min ${minimum} · Max ${maximum} · Mean ${mean}`;
  return {
    caption: `${receipt.variable}${position}`,
    time_header: t?.('series.timeHeader', { unit: timeUnit }) ?? `Time${timeUnit}`,
    value_header: `${receipt.variable}${valueUnit}`,
    rows,
    row_summary: `${rowSummary}${rowSample}`,
    ...(hasAnalysis ? { analysis_summary: analysisSummary } : {}),
    truncated,
  };
}

export const SERIES_TABLE_ROW_HEIGHT = 33;
export const SERIES_TABLE_OVERSCAN = 8;

/** Virtualised window into a long trace: start index, visible slice, and the
    top/bottom spacer heights for a fixed row height. Pure for node tests. */
export function seriesTableWindow(
  rowCount: number,
  scrollTop: number,
  viewportHeight: number,
  rowHeight: number = SERIES_TABLE_ROW_HEIGHT,
  overscan: number = SERIES_TABLE_OVERSCAN,
): { start: number; end: number; topSpacer: number; bottomSpacer: number } {
  const safeCount = Math.max(0, Math.floor(rowCount));
  if (safeCount === 0) return { start: 0, end: 0, topSpacer: 0, bottomSpacer: 0 };
  const safeRow = Math.max(1, rowHeight);
  const first = Math.max(0, Math.floor(Math.max(0, scrollTop) / safeRow) - overscan);
  const visible = Math.max(1, Math.ceil(Math.max(0, viewportHeight) / safeRow) + overscan * 2);
  const start = Math.min(first, safeCount);
  const end = Math.min(safeCount, start + visible);
  return { start, end, topSpacer: start * safeRow, bottomSpacer: (safeCount - end) * safeRow };
}

function safeFilename(value: string): string {
  const segments = value.replaceAll('\\', '/').split('/').filter(Boolean);
  return segments[segments.length - 1] || 'artifact';
}

function normalizeArtifactReceipt(value: unknown): ArtifactReceiptView | null {
  if (!isRecord(value)) return null;
  if (typeof value.artifact_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.artifact_id)) return null;
  if (typeof value.kind !== 'string' || typeof value.mime !== 'string') return null;
  if (typeof value.suggested_filename !== 'string' || typeof value.sha256 !== 'string') return null;
  const lineage = isRecord(value.lineage) ? value.lineage : undefined;
  const resultId = lineage && typeof lineage.source_id === 'string'
    ? lineage.source_id
    : lineage && typeof lineage.result_id === 'string'
      ? lineage.result_id
      : undefined;
  return {
    artifact_id: value.artifact_id,
    kind: value.kind,
    mime: value.mime,
    suggested_filename: safeFilename(value.suggested_filename),
    sha256: value.sha256,
    ...(typeof value.size === 'number' ? { size: value.size } : {}),
    ...(typeof value.size_bytes === 'number' ? { size_bytes: value.size_bytes } : {}),
    ...(lineage ? { lineage } : {}),
    ...(resultId ? { result_id: resultId } : {}),
    ...(typeof value.workspace_generation === 'number' ? { workspace_generation: value.workspace_generation } : {}),
    ...(Array.isArray(value.actions) ? { actions: value.actions.filter((action): action is string => typeof action === 'string') } : {}),
  };
}

function artifactActions(receipt: ArtifactReceiptView): readonly ArtifactAction[] {
  const actions = receipt.actions;
  if (!actions) return [
    { kind: 'save-as', artifact_id: receipt.artifact_id },
    { kind: 'open-results', artifact_id: receipt.artifact_id },
  ];
  return actions.flatMap((action): readonly ArtifactAction[] => {
    if (action === 'download') return [{ kind: 'download', artifact_id: receipt.artifact_id }];
    if (action === 'open_in_results') return [{ kind: 'open-results', artifact_id: receipt.artifact_id }];
    if (action === 'native_save_as') return [{ kind: 'save-as', artifact_id: receipt.artifact_id }];
    return [];
  });
}

export function presentArtifactReceipt(value: unknown, currentGeneration?: number): ArtifactPresentation | null {
  const receipt = normalizeArtifactReceipt(value);
  if (!receipt) return null;
  const readOnly = currentGeneration !== undefined
    && receipt.workspace_generation !== undefined
    && receipt.workspace_generation !== currentGeneration;
  return readOnly
    ? { receipt, actions: [], read_only: true }
    : { receipt, actions: artifactActions(receipt) };
}

export function isArtifactReceipt(value: unknown): boolean {
  if (!isRecord(value) || !/^artifact_[0-9a-f]{32}$/.test(String(value.artifact_id ?? ''))) return false;
  if (!Number.isInteger(value.size_bytes) || Number(value.size_bytes) < 0) return false;
  if (typeof value.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.sha256)) return false;
  if (typeof value.workspace_generation !== 'number' || !Number.isInteger(value.workspace_generation) || value.workspace_generation < 0) return false;
  if (!isRecord(value.lineage) || typeof value.lineage.source_id !== 'string') return false;
  if (value.lineage.source_kind !== 'workspace' && value.lineage.source_kind !== 'run') return false;
  if (!Array.isArray(value.actions) || value.actions.length === 0) return false;
  const validActions = value.actions.every((action) => (
    action === 'download' || action === 'open_in_results' || action === 'native_save_as'
  ));
  if (!validActions) return false;
  return (value.kind === 'csv' && value.mime === 'text/csv')
    || (value.kind === 'png' && value.mime === 'image/png')
    || (value.kind === 'pdf' && value.mime === 'application/pdf');
}
