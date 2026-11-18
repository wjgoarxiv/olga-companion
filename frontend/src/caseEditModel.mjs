// The user's own value table for one case: shows each value in an engineer's unit and turns
// the cells the user changed into edit operations of the closed grammar the server checks.

const UNITS = {
  end_time_s: { unit: 's', scale: 1 },
  pressure_pa: { unit: 'bar', scale: 1e-5 },
  temperature_c: { unit: '°C', scale: 1 },
  mass_flow_kg_s: { unit: 'kg/s', scale: 1 },
  opening: { unit: '%', scale: 100 },
  roughness_m: { unit: 'mm', scale: 1000 },
};

function unitOf(field) {
  return UNITS[field] ?? { unit: '', scale: 1 };
}

export function displayUnit(field) {
  return unitOf(field).unit;
}

/** The stored value shown in the display unit, without float noise such as 4.000000000001. */
export function displayValue(row) {
  return Number((row.value * unitOf(row.field).scale).toPrecision(12));
}

export function formatDisplay(row) {
  return String(displayValue(row));
}

/** Parse one cell typed in the display unit; a comma decimal is accepted. */
/** The limits the case grammar accepts, in SI (case_spec_types.py); a cell outside them is refused before review. */
const RANGES = {
  end_time_s: { low: (v) => v > 0, max: 31_536_000 },
  pressure_pa: { low: (v) => v > 0, max: 1_000_000_000 },
  temperature_c: { low: (v) => v > -273.15, max: 1_500 },
  mass_flow_kg_s: { low: (v) => v >= 0, max: 1_000_000 },
  roughness_m: { low: (v) => v >= 0, max: 0.1 },
};

export function parseCell(field, text) {
  const trimmed = String(text ?? '').trim().replace(',', '.');
  if (trimmed === '' || !/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(trimmed)) {
    return { ok: false, error: 'caseEdit.error.notNumber' };
  }
  const shown = Number(trimmed);
  if (!Number.isFinite(shown)) return { ok: false, error: 'caseEdit.error.notNumber' };
  if (field === 'opening' && (shown < 0 || shown > 100)) return { ok: false, error: 'caseEdit.error.openingRange' };
  const value = Number((shown / unitOf(field).scale).toPrecision(15));
  const range = RANGES[field];
  if (range && !(range.low(value) && value <= range.max)) return { ok: false, error: `caseEdit.error.range.${field}` };
  return { ok: true, value };
}

/** Rows whose draft differs from the case value; an unchanged or blank cell is no edit. */
export function changedRows(rows, drafts) {
  return rows.filter((row) => {
    const draft = drafts[row.id];
    if (draft === undefined || String(draft).trim() === '') return false;
    const parsed = parseCell(row.field, draft);
    return !parsed.ok || parsed.value !== row.value;
  });
}

/** Operations for the changed cells, or the first cell error to show next to its row. */
export function buildOperations(rows, drafts) {
  const operations = [];
  for (const row of changedRows(rows, drafts)) {
    const parsed = parseCell(row.field, drafts[row.id]);
    if (!parsed.ok) return { ok: false, rowId: row.id, error: parsed.error };
    operations.push({ ...row.op, [row.field]: parsed.value });
  }
  if (operations.length === 0) return { ok: false, rowId: null, error: 'caseEdit.error.nothingChanged' };
  return { ok: true, operations };
}

const CONFLICTS = {
  stale_source: 'caseEdit.conflict.source',
  stale_context: 'caseEdit.conflict.context',
};

/** The sentence for a conflict the server reports; null when it is not a conflict. */
export function conflictKey(code) {
  return CONFLICTS[code] ?? null;
}

/** Readable reasons from a plan the server could not make publishable. */
export function planReasons(plan) {
  const reasons = [];
  for (const issue of plan?.errors ?? []) {
    if (issue && typeof issue.message === 'string' && issue.message) reasons.push(issue.message);
  }
  for (const line of plan?.validation?.diagnostics ?? []) {
    if (typeof line === 'string' && line) reasons.push(line);
  }
  return reasons;
}
