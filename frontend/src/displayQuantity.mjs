import { formatUnit } from './formatUnit.mjs';

// OLGA's own unit spellings and the unit the app shows them in. Display only: files keep OLGA's bytes.
const RULES = {
  pa: { unit: 'bar', scale: 1e-5 },
  kpa: { unit: 'bar', scale: 1e-2 },
  mpa: { unit: 'bar', scale: 10 },
  c: { unit: '°C', scale: 1 },
  k: { unit: '°C', scale: 1, offset: -273.15 },
  'kg/s': { unit: 'kg/s', scale: 1 },
  'm3/s': { unit: 'm3/s', scale: 1 },
};

const clean = (value) => Number(value.toPrecision(12));
const ruleFor = (unit) => RULES[String(unit ?? '').trim().toLowerCase()];

function convert(value, rawUnit, withOffset) {
  const unit = String(rawUnit ?? '').trim();
  const raw = `${value} ${unit}`.trim();
  const rule = ruleFor(unit);
  if (!rule || typeof value !== 'number' || !Number.isFinite(value)) {
    return { value, unit: unit ? formatUnit(unit) : '', raw, converted: false };
  }
  return { value: clean(value * rule.scale + (withOffset ? rule.offset ?? 0 : 0)), unit: rule.unit, raw, converted: true };
}

/** A value in the unit the app shows, with the OLGA value and unit kept as `raw`. */
export function toDisplay(value, rawUnit) {
  return convert(value, rawUnit, true);
}

/** A difference between two values: scaled like a value, without a temperature offset. */
export function toDisplayDelta(value, rawUnit) {
  return convert(value, rawUnit, false);
}

/** The OLGA value for a shown one, so a shown value always maps back to what the file holds. */
export function toRaw(shown, rawUnit) {
  const rule = ruleFor(rawUnit);
  if (!rule) return shown;
  return clean((shown - (rule.offset ?? 0)) / rule.scale);
}

/** "2500000 PA" from a case file shown as "25 bar"; text that is not one number and a unit the app
    converts stays as written. */
export function displayFromText(text) {
  const match = /^(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s+(\S+)$/i.exec(String(text ?? '').trim());
  if (!match) return String(text ?? '');
  const quantity = toDisplay(Number(match[1]), match[2]);
  return quantity.converted ? displayText(quantity) : String(text);
}

/** Short text for a shown value: six significant figures, with its display unit. */
export function displayText(quantity) {
  const shown = typeof quantity.value === 'number' ? String(Number(quantity.value.toPrecision(6))) : String(quantity.value ?? '');
  return quantity.unit ? `${shown} ${quantity.unit}` : shown;
}
