export const MAX_SWEEP_CASES = 20;

export function splitSweepValues(value) {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function parseSweepValue(value) {
  const match = value.trim().match(/^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)\s*(.*)$/i);
  if (!match) return null;
  const numericValue = Number(match[1]);
  return Number.isFinite(numericValue) ? { value: numericValue, unit: match[2].trim() } : null;
}

export function readRangeSweepValues(value, fallback) {
  const values = splitSweepValues(value);
  const first = parseSweepValue(values[0] ?? '');
  const last = parseSweepValue(values[values.length - 1] ?? '');
  if (!first || !last) return fallback;
  return {
    start: first.value,
    stop: last.value,
    count: Math.max(2, Math.min(MAX_SWEEP_CASES, values.length)),
    unit: first.unit,
  };
}

function formatRangeValue(value, unit) {
  const rounded = Math.round(value * 1_000_000) / 1_000_000;
  return unit.trim() ? `${rounded} ${unit.trim()}` : String(rounded);
}

export function buildRangeSweepValues({ start, stop, count, unit }) {
  if (!Number.isFinite(start) || !Number.isFinite(stop) || !Number.isInteger(count)) return '';
  if (count < 2 || count > MAX_SWEEP_CASES) return '';
  const step = (stop - start) / (count - 1);
  return Array.from({ length: count }, (_, index) => formatRangeValue(start + step * index, unit)).join(',');
}
