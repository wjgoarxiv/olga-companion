import { unitChoicesForDimension } from './unitPreferences.mjs';

// Display-only labels (C renders as °C, dimensionless as "-"); raw OLGA
// codes are never reshaped, and this stays out of the approval card.
const DIMENSIONS = [
  'pressure',
  'temperature',
  'time',
  'mass_flow',
  'volume_flow',
  'length',
  'velocity',
  'dimensionless',
];

const CASING = new Map();
for (const dimension of DIMENSIONS) {
  for (const unit of unitChoicesForDimension(dimension)) {
    CASING.set(unit.toLowerCase(), unit);
  }
}

const DISPLAY_OVERRIDES = {
  C: '°C',
  celsius: '°C',
  fraction: '-',
  dimensionless: '-',
  1: '-',
};

export function formatUnit(unit) {
  if (typeof unit !== 'string') return '-';
  const trimmed = unit.trim();
  if (trimmed === '') return '-';
  if (Object.prototype.hasOwnProperty.call(DISPLAY_OVERRIDES, trimmed)) {
    return DISPLAY_OVERRIDES[trimmed];
  }
  return CASING.get(trimmed.toLowerCase()) ?? trimmed;
}
