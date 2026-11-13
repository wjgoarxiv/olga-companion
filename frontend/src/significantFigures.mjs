export const SIGNIFICANT_FIGURE_OPTIONS = Object.freeze([3, 4, 5, 6]);
export const DEFAULT_SIGNIFICANT_FIGURES = 5;
export const SIGNIFICANT_FIGURES_KEY = 'olga-companion.significant-figures.v1';

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseSignificantFigures(value) {
  if (value === 3 || value === '3') return 3;
  if (value === 4 || value === '4') return 4;
  if (value === 5 || value === '5') return 5;
  if (value === 6 || value === '6') return 6;
  return null;
}

function browserStorage() {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function loadSignificantFigures(storage = browserStorage()) {
  try {
    const raw = storage?.getItem(SIGNIFICANT_FIGURES_KEY);
    if (raw === null || raw === undefined) return DEFAULT_SIGNIFICANT_FIGURES;
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.version !== 1) return DEFAULT_SIGNIFICANT_FIGURES;
    return parseSignificantFigures(parsed.significantFigures) ?? DEFAULT_SIGNIFICANT_FIGURES;
  } catch {
    return DEFAULT_SIGNIFICANT_FIGURES;
  }
}

export function saveSignificantFigures(significantFigures, storage = browserStorage()) {
  try {
    storage?.setItem(SIGNIFICANT_FIGURES_KEY, JSON.stringify({ version: 1, significantFigures }));
    return storage !== undefined;
  } catch {
    return false;
  }
}

export function formatSignificant(value, significantFigures) {
  if (!Number.isFinite(value)) return 'unavailable';
  if (value === 0) return '0';
  const rounded = Number(value.toPrecision(significantFigures));
  const magnitude = Math.abs(rounded);
  if (magnitude < 0.0001 || magnitude >= 10_000_000) {
    return rounded.toExponential(significantFigures - 1).replace('e+', 'e');
  }
  return rounded.toLocaleString('en-US', { maximumFractionDigits: 20 });
}

// Series values: the chosen precision, raised until the series' own span spans
// about ten steps (101,325-101,650 Pa at 3 figures would all read 102,000).
export function figuresForSpan(minimum, maximum, significantFigures) {
  const span = Math.abs(maximum - minimum);
  const magnitude = Math.max(Math.abs(minimum), Math.abs(maximum));
  if (!Number.isFinite(span) || !Number.isFinite(magnitude) || span === 0 || magnitude === 0) {
    return significantFigures;
  }
  const needed = Math.ceil(Math.log10(magnitude / span)) + 2;
  return Math.min(15, Math.max(significantFigures, needed));
}

// Axis labels: the chosen precision, raised only as far as it takes for
// neighbouring ticks to read differently (20 Pa apart at 3 figures is 101,000 x3).
export function formatDistinctTicks(values, significantFigures) {
  for (let figures = significantFigures; figures <= 15; figures += 1) {
    const labels = values.map((value) => formatSignificant(value, figures));
    if (new Set(labels).size === labels.length) return labels;
  }
  return values.map((value) => formatSignificant(value, 15));
}
