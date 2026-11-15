export const UNIT_PREFERENCES_VERSION = 1;
export const UNIT_PREFERENCES_KEY = 'olga-companion.unit-preferences.v1';

const DIMENSION = /^[a-z][a-z0-9_]{0,31}$/;
const UNIT = /^[A-Za-z0-9%°_./*^+ -]{1,64}$/;
const BLOCKED_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
const UNIT_CHOICES = Object.freeze(Object.assign(Object.create(null), {
  pressure: Object.freeze(['Pa', 'kPa', 'MPa', 'bar', 'psi']),
  temperature: Object.freeze(['K', 'C', 'F']),
  time: Object.freeze(['s', 'min', 'h']),
  mass_flow: Object.freeze(['kg/s', 'kg/h', 't/h', 'lb/h']),
  volume_flow: Object.freeze(['m3/s', 'm3/h', 'L/s']),
  length: Object.freeze(['m', 'mm', 'km', 'ft']),
  velocity: Object.freeze(['m/s', 'ft/s']),
  dimensionless: Object.freeze(['fraction', '%']),
}));

function defaults() {
  return { version: UNIT_PREFERENCES_VERSION, valueUnits: {}, timeUnit: null };
}

function validUnit(value) {
  return typeof value === 'string' && value === value.trim() && UNIT.test(value);
}

function approvedUnit(dimension, unit) {
  if (!Object.prototype.hasOwnProperty.call(UNIT_CHOICES, dimension) || !validUnit(unit)) return undefined;
  return UNIT_CHOICES[dimension].find((candidate) => candidate === unit);
}

function normalize(input) {
  try {
    if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
    if (input.version !== UNIT_PREFERENCES_VERSION) return null;
    if (!input.valueUnits || typeof input.valueUnits !== 'object' || Array.isArray(input.valueUnits)) return null;
    if (input.timeUnit !== null && !approvedUnit('time', input.timeUnit)) return null;
    const valueUnits = {};
    for (const [dimension, unit] of Object.entries(input.valueUnits)) {
      const canonical = approvedUnit(dimension, unit);
      if (!DIMENSION.test(dimension) || BLOCKED_KEYS.has(dimension) || !canonical) return null;
      valueUnits[dimension] = canonical;
    }
    return { version: UNIT_PREFERENCES_VERSION, valueUnits, timeUnit: input.timeUnit };
  } catch {
    return null;
  }
}

function browserStorage() {
  try {
    return globalThis.localStorage;
  } catch {
    return undefined;
  }
}

function persist(storage, preferences) {
  try {
    storage?.setItem(UNIT_PREFERENCES_KEY, JSON.stringify(preferences));
    return Boolean(storage?.setItem);
  } catch {
    return false;
  }
}

export function loadUnitPreferences(storage) {
  const target = storage || browserStorage();
  const fallback = defaults();
  try {
    const raw = target?.getItem(UNIT_PREFERENCES_KEY);
    if (raw != null) {
      const parsed = normalize(JSON.parse(raw));
      if (parsed) return parsed;
    }
  } catch {
    // Storage and JSON failures are equivalent to a missing preference.
  }
  persist(target, fallback);
  return fallback;
}

export function saveUnitPreferences(storage, preferences) {
  const normalized = normalize(preferences);
  if (!normalized) return false;
  return persist(storage || browserStorage(), normalized);
}

export function setValueUnitPreference(preferences, dimension, unit) {
  const current = normalize(preferences) || defaults();
  const canonical = approvedUnit(dimension, unit);
  if (!DIMENSION.test(dimension) || BLOCKED_KEYS.has(dimension) || !canonical) return current;
  return {
    ...current,
    valueUnits: { ...current.valueUnits, [dimension]: canonical },
  };
}

export function setTimeUnitPreference(preferences, unit) {
  const current = normalize(preferences) || defaults();
  const canonical = approvedUnit('time', unit);
  if (!canonical) return current;
  return { ...current, timeUnit: canonical };
}

export function unitChoicesForDimension(dimension) {
  return [...(Object.prototype.hasOwnProperty.call(UNIT_CHOICES, dimension) ? UNIT_CHOICES[dimension] : [])];
}

function canonicalSource(dimension, sourceUnit) {
  if (!dimension || !validUnit(sourceUnit)) return undefined;
  return Object.prototype.hasOwnProperty.call(UNIT_CHOICES, dimension)
    ? UNIT_CHOICES[dimension].find((unit) => unit.toLowerCase() === sourceUnit.toLowerCase())
    : undefined;
}

export function preferredSeriesView(preferences, valueConversion, timeConversion) {
  const current = normalize(preferences) || defaults();
  const dimension = valueConversion?.dimension;
  const valueUnit = dimension
    ? current.valueUnits[dimension] || canonicalSource(dimension, valueConversion?.source_unit)
    : undefined;
  const timeUnit = timeConversion?.dimension === 'time'
    ? current.timeUnit || canonicalSource('time', timeConversion?.source_unit)
    : undefined;
  return {
    ...(valueUnit ? { value_unit: valueUnit } : {}),
    ...(timeUnit ? { time_unit: timeUnit } : {}),
    quantity_kind: 'point',
    range: { mode: 'full' },
  };
}

export function discoveryMatchesPreferredView(discovered, preferredView) {
  const valueConversion = discovered?.view?.value_conversion;
  const timeConversion = discovered?.view?.time_conversion;
  const range = discovered?.view?.range;
  if (!valueConversion || !timeConversion || range?.mode !== 'full' || preferredView?.range?.mode !== 'full') return false;
  if (valueConversion.quantity_kind !== preferredView.quantity_kind) return false;
  if (preferredView.value_unit !== undefined) {
    if (valueConversion.status === 'source_only') return false;
    if (discovered.unit !== preferredView.value_unit || valueConversion.output_unit !== preferredView.value_unit) return false;
  }
  if (preferredView.time_unit !== undefined) {
    if (timeConversion.status === 'source_only') return false;
    if (discovered.time_unit !== preferredView.time_unit || timeConversion.output_unit !== preferredView.time_unit) return false;
  }
  return true;
}

export function acceptSeriesUnitPreferences(preferences, valueConversion, timeConversion) {
  const normalized = normalize(preferences);
  const current = normalized || defaults();
  const acceptedStatuses = new Set(['converted', 'identity', 'not_requested']);
  const valueUnit = acceptedStatuses.has(valueConversion?.status)
    ? approvedUnit(valueConversion?.dimension, valueConversion?.output_unit)
    : undefined;
  const timeUnit = acceptedStatuses.has(timeConversion?.status) && timeConversion?.dimension === 'time'
    ? approvedUnit('time', timeConversion?.output_unit)
    : undefined;
  const next = {
    ...current,
    valueUnits: valueUnit
      ? { ...current.valueUnits, [valueConversion.dimension]: valueUnit }
      : current.valueUnits,
    timeUnit: timeUnit || current.timeUnit,
  };
  const unchanged = next.timeUnit === current.timeUnit
    && Object.keys(next.valueUnits).length === Object.keys(current.valueUnits).length
    && Object.entries(next.valueUnits).every(([dimension, unit]) => current.valueUnits[dimension] === unit);
  return unchanged && normalized ? preferences : next;
}
