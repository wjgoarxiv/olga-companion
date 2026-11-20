import { parseStrictNumber } from './strictNumber.mjs';
// The user's own value table for one case: shows each value in an engineer's unit and turns
// the cells the user changed into edit operations of the closed grammar the server checks.

const UNITS = {
  end_time_s: { unit: 's', scale: 1 },
  pressure_pa: { unit: 'bar', scale: 1e-5 },
  temperature_c: { unit: '°C', scale: 1 },
  mass_flow_kg_s: { unit: 'kg/s', scale: 1 },
  opening: { unit: '%', scale: 100 },
  roughness_m: { unit: 'mm', scale: 1000 },
  diameter_m: { unit: 'mm', scale: 1000 },
  max_dt_s: { unit: 's', scale: 1 },
  min_dt_s: { unit: 's', scale: 1 },
  dt_start_s: { unit: 's', scale: 1 },
  trend_interval_s: { unit: 's', scale: 1 },
  profile_interval_s: { unit: 's', scale: 1 },
  output_interval_s: { unit: 's', scale: 1 },
  ambient_temperature_c: { unit: '°C', scale: 1 },
  outer_heat_transfer_coefficient_w_m2k: { unit: 'W/m²K', scale: 1 },
  wall_thickness_m: { unit: 'mm', scale: 1000 },
  wall_conductivity_w_mk: { unit: 'W/m·K', scale: 1 },
  wall_heat_capacity_j_kgk: { unit: 'J/kg·K', scale: 1 },
  wall_density_kg_m3: { unit: 'kg/m³', scale: 1 },
};

function unitOf(field) {
  return UNITS[field] ?? { unit: '', scale: 1 };
}

export function displayUnit(field) {
  return unitOf(field).unit;
}

/** The stored value shown in the display unit, without float noise such as 4.000000000001.
    null when the case leaves the value out and nothing is derived (MAXDT). */
export function displayValue(row) {
  if (row.value === null || row.value === undefined) return null;
  return Number((row.value * unitOf(row.field).scale).toPrecision(12));
}

export function formatDisplay(row) {
  const shown = displayValue(row);
  return shown === null ? '' : String(shown);
}

/** Parse one cell typed in the display unit; a comma decimal is accepted. */
/** The limits the case grammar accepts, in SI (case_spec_types.py); a cell outside them is refused before review. */
const RANGES = {
  end_time_s: { low: (v) => v > 0, max: 31_536_000 },
  pressure_pa: { low: (v) => v > 0, max: 1_000_000_000 },
  temperature_c: { low: (v) => v > -273.15, max: 1_500 },
  mass_flow_kg_s: { low: (v) => v >= 0, max: 1_000_000 },
  roughness_m: { low: (v) => v >= 0, max: 0.1 },
  diameter_m: { low: (v) => v > 0, max: 10 },
  max_dt_s: { low: (v) => v > 0, max: 31_536_000 },
  min_dt_s: { low: (v) => v > 0, max: 31_536_000 },
  dt_start_s: { low: (v) => v > 0, max: 31_536_000 },
  trend_interval_s: { low: (v) => v > 0, max: 31_536_000 },
  profile_interval_s: { low: (v) => v > 0, max: 31_536_000 },
  output_interval_s: { low: (v) => v > 0, max: 31_536_000 },
  ambient_temperature_c: { low: (v) => v > -273.15, max: 1_500 },
  outer_heat_transfer_coefficient_w_m2k: { low: (v) => v > 0, max: 100_000 },
  wall_thickness_m: { low: (v) => v > 0, max: 1 },
  wall_conductivity_w_mk: { low: (v) => v > 0, max: 1_000 },
  wall_heat_capacity_j_kgk: { low: (v) => v > 0, max: 100_000 },
  wall_density_kg_m3: { low: (v) => v > 0, max: 30_000 },
};

export function parseCell(field, text) {
  // "1,500" could be 1500 or 1.5, so it is refused; "0,5" is a decimal comma.
  const shown = parseStrictNumber(String(text ?? ''));
  if (shown === null) return { ok: false, error: 'caseEdit.error.notNumber' };
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
    // The prefilled text is the stored value rounded for display; leaving it alone is no edit.
    if (String(draft).trim() === formatDisplay(row)) return false;
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
