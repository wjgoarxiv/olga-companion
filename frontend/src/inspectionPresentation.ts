import type { I18nKey } from './i18n/ko.ts';

type Result = Record<string, unknown>;

export type InspectionText = (key: I18nKey, vars?: Record<string, string | number>) => string;

type ReviewCheck = {
  readonly label: string;
  readonly state: string;
  readonly detail: string;
  readonly report?: string;
};

export type GenkeyReviewPresentation = {
  readonly kind: 'genkey';
  readonly good: boolean;
  readonly title: string;
  readonly detail: string;
  readonly source?: string;
  readonly checks: readonly ReviewCheck[];
};

type PvtComponent = {
  readonly name: string;
  readonly fraction: string;
  readonly molarMass?: string;
};

type PvtMetric = {
  readonly label: string;
  readonly value: string;
  readonly unit?: string;
  readonly note?: string;
};

/** Section/line labels parsed from English PVT validator output; the parser
 *  keys off these exact spellings, so they stay constants, never translations. */
const MOL_WEIGHTS_SECTION = 'Mol Weights';
const MESH_TYPE_LINE = 'Mesh Type';

export type PvtInspectionPresentation = {
  readonly kind: 'pvt';
  readonly good: boolean;
  readonly title: string;
  readonly label: string;
  readonly phase: string;
  readonly formulation: string;
  readonly components: readonly PvtComponent[];
  readonly metrics: readonly PvtMetric[];
  readonly errorCount: number;
  readonly warningCount: number;
  readonly rawSummary: string;
};

export type InspectionPresentation = GenkeyReviewPresentation | PvtInspectionPresentation;

function record(value: unknown): Result | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value))
    : null;
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function safeSource(value: unknown): string | undefined {
  const source = str(value);
  if (!source) return undefined;
  const segments = source.replaceAll('\\', '/').split('/').filter(Boolean);
  return segments[segments.length - 1] ?? source;
}

function report(result: Result, key: string): string | undefined {
  return str(record(result[key])?.stdout)?.slice(0, 4_000);
}

function exitCode(result: Result, key: string): number | undefined {
  const value = record(result[key])?.exit_code;
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function presentGenkeyReview(result: Result, t: InspectionText | null): GenkeyReviewPresentation {
  const text = (key: I18nKey): string | null => (t ? t(key) : null);
  const validationExit = exitCode(result, 'validation');
  const topologyExit = exitCode(result, 'topology');
  const validationFailed = validationExit !== undefined && validationExit !== 0;
  const topologyFailed = topologyExit !== undefined && topologyExit !== 0;
  const good = result.valid === true && !validationFailed && !topologyFailed;
  const source = safeSource(result.path);
  return {
    kind: 'genkey',
    good,
    title: good
      ? text('inspect.genkey.passTitle') ?? '사례 검증 통과'
      : text('inspect.genkey.attentionTitle') ?? '사례 검토가 필요해요',
    detail: good
      ? text('inspect.genkey.passDetail') ?? '검증과 배관망 검사를 마쳤고, 진행을 막는 문제는 없었어요.'
      : text('inspect.genkey.attentionDetail') ?? '확인 결과 살펴볼 점이 있어요.',
    ...(source ? { source } : {}),
    checks: [
      {
        label: text('inspect.check.rules') ?? '사례 규칙',
        state: validationExit === 0
          ? text('inspect.state.pass') ?? '통과'
          : validationExit === undefined
            ? text('inspect.state.reviewed') ?? '검토함'
            : text('inspect.state.attention') ?? '확인 필요',
        detail: validationExit === 0
          ? text('inspect.check.genkeyDone') ?? 'GENKEY 검증이 끝났어요.'
          : text('inspect.check.genkeyTodo') ?? '이 사례를 쓰기 전에 검증 보고서를 확인하세요.',
        ...(report(result, 'validation') ? { report: report(result, 'validation') } : {}),
      },
      {
        label: text('inspect.check.topology') ?? '배관망 구조',
        state: topologyExit === 0
          ? text('inspect.state.read') ?? '읽음'
          : topologyExit === undefined
            ? text('inspect.state.reviewed') ?? '검토함'
            : text('inspect.state.attention') ?? '확인 필요',
        detail: topologyExit === 0
          ? text('inspect.check.topoDone') ?? '배관망 연결을 읽었어요.'
          : text('inspect.check.topoTodo') ?? '빠지거나 잘못된 연결이 있는지 보고서를 확인하세요.',
        ...(report(result, 'topology') ? { report: report(result, 'topology') } : {}),
      },
    ],
  };
}

function line(summary: string, label: string): string | undefined {
  const found = summary.match(new RegExp(`^\\s*${label}:\\s*(.+?)\\s*$`, 'mi'));
  return found?.[1]?.trim();
}

function titleCase(value: string): string {
  const lower = value.toLowerCase();
  return `${lower.slice(0, 1).toUpperCase()}${lower.slice(1)}`;
}

function displayNumber(value: string): string {
  return value.startsWith('-') ? `−${value.slice(1)}` : value;
}

function parseComponents(summary: string): readonly PvtComponent[] {
  const componentLine = line(summary, 'Components') ?? '';
  const weightLine = line(summary, MOL_WEIGHTS_SECTION) ?? '';
  const weights: Record<string, string> = {};
  for (const match of weightLine.matchAll(/([A-Za-z0-9_+\-]+)\s*=\s*([-+\d.Ee]+)/g)) {
    const name = match[1];
    const value = match[2];
    if (name && value) weights[name] = value;
  }
  return [...componentLine.matchAll(/([A-Za-z0-9_+\-]+)\s*\(([-+\d.Ee]+)\s*mol%\)/g)]
    .flatMap((match): readonly PvtComponent[] => {
      const name = match[1];
      const fraction = match[2];
      if (!name || !fraction) return [];
      return [{
        name,
        fraction: `${fraction} mol%`,
        ...(weights[name] ? { molarMass: weights[name] } : {}),
      }];
    });
}

function parseRangeMetric(
  summary: string,
  sourceLabel: string,
  metricLabel: string,
  unitOverride?: string,
): PvtMetric | null {
  const raw = line(summary, sourceLabel);
  const match = raw?.match(/^([-+\d.Ee]+)\s*-\s*([-+\d.Ee]+)\s+(\S+)(?:\s+\(([^)]+)\))?$/);
  if (!match?.[1] || !match[2] || !match[3]) return null;
  return {
    label: metricLabel,
    value: `${displayNumber(match[1])}–${displayNumber(match[2])}`,
    unit: unitOverride ?? match[3],
    ...(match[4] ? { note: match[4] } : {}),
  };
}

function presentPvtInspection(result: Result, t: InspectionText | null): PvtInspectionPresentation | null {
  const text = (key: I18nKey): string | null => (t ? t(key) : null);
  const summary = str(result.summary_text);
  if (!summary) return null;
  const title = line(summary, 'PVT Table Summary');
  if (!title) return null;
  const pressure = parseRangeMetric(summary, 'Pressure', 'Pressure envelope');
  const temperature = parseRangeMetric(summary, 'Temperature', 'Temperature envelope', '°C');
  const mesh = line(summary, MESH_TYPE_LINE);
  const size = line(summary, 'File Size')?.match(/^([-\d.]+)\s*(\S+)$/);
  const metrics: PvtMetric[] = [];
  if (pressure) metrics.push(pressure);
  if (temperature) metrics.push(temperature);
  if (mesh) metrics.push({ label: 'Mesh', value: titleCase(mesh) });
  if (size?.[1]) metrics.push({ label: 'File size', value: size[1], ...(size[2] ? { unit: size[2] } : {}) });
  return {
    kind: 'pvt',
    good: result.valid === true,
    title,
    label: line(summary, 'Label') ?? text('inspect.pvt.unlabelled') ?? 'Unlabelled table',
    phase: line(summary, 'Phase') ?? text('inspect.unknownValue') ?? 'Unknown',
    formulation: titleCase((line(summary, 'Formulation') ?? text('inspect.unknownValue') ?? 'Unknown').replace(/^\((.+)\)$/, '$1')),
    components: parseComponents(summary),
    metrics,
    errorCount: Array.isArray(result.validation_errors) ? result.validation_errors.length : 0,
    warningCount: Array.isArray(result.validation_warnings) ? result.validation_warnings.length : 0,
    rawSummary: summary.slice(0, 6_000),
  };
}

export function presentInspectionEvidence(name: string, result: Result, t: InspectionText | null = null): InspectionPresentation | null {
  if (name === 'genkey_review') return presentGenkeyReview(result, t);
  if (name === 'fluids_inspect_tab') return presentPvtInspection(result, t);
  return null;
}
