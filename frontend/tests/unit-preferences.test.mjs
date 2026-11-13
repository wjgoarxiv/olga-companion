import test from 'node:test';
import assert from 'node:assert/strict';

import {
  acceptSeriesUnitPreferences,
  discoveryMatchesPreferredView,
  UNIT_PREFERENCES_KEY,
  UNIT_PREFERENCES_VERSION,
  loadUnitPreferences,
  preferredSeriesView,
  saveUnitPreferences,
  setTimeUnitPreference,
  setValueUnitPreference,
  unitChoicesForDimension,
} from '../src/unitPreferences.mjs';

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key) { return data.has(key) ? data.get(key) : null; },
    setItem(key, value) { data.set(key, String(value)); },
    removeItem(key) { data.delete(key); },
    value(key) { return data.get(key); },
  };
}

const defaults = { version: UNIT_PREFERENCES_VERSION, valueUnits: {}, timeUnit: null };

test('missing, corrupt, and unsupported preference versions reset to safe defaults', () => {
  for (const stored of [
    undefined,
    '{not-json',
    JSON.stringify({ version: UNIT_PREFERENCES_VERSION + 1, valueUnits: { pressure: 'bar' }, timeUnit: 'min' }),
    JSON.stringify({ version: UNIT_PREFERENCES_VERSION, valueUnits: [], timeUnit: 'min' }),
    JSON.stringify({ version: UNIT_PREFERENCES_VERSION, valueUnits: { pressure: 42 }, timeUnit: 'min' }),
  ]) {
    const storage = memoryStorage(stored === undefined ? {} : { [UNIT_PREFERENCES_KEY]: stored });
    assert.deepEqual(loadUnitPreferences(storage), defaults);
    assert.deepEqual(JSON.parse(storage.value(UNIT_PREFERENCES_KEY)), defaults);
  }
});

test('dimension-unsupported, mismatched, and unknown saved units reset the whole preference record', () => {
  for (const value of [
    { version: UNIT_PREFERENCES_VERSION, valueUnits: { pressure: 'bananas' }, timeUnit: 'min' },
    { version: UNIT_PREFERENCES_VERSION, valueUnits: { pressure: 'h' }, timeUnit: 'min' },
    { version: UNIT_PREFERENCES_VERSION, valueUnits: { mystery: 'bar' }, timeUnit: 'min' },
    { version: UNIT_PREFERENCES_VERSION, valueUnits: { pressure: 'bar' }, timeUnit: 'fortnight' },
    JSON.parse('{"version":1,"valueUnits":{"__proto__":"bar"},"timeUnit":"min"}'),
  ]) {
    const storage = memoryStorage({ [UNIT_PREFERENCES_KEY]: JSON.stringify(value) });
    assert.deepEqual(loadUnitPreferences(storage), defaults);
    assert.deepEqual(JSON.parse(storage.value(UNIT_PREFERENCES_KEY)), defaults);
  }
});

test('preferences persist units only, keyed by backend dimension plus one time unit', () => {
  const storage = memoryStorage();
  let preferences = loadUnitPreferences(storage);
  preferences = setValueUnitPreference(preferences, 'pressure', 'bar');
  preferences = setValueUnitPreference(preferences, 'temperature', 'F');
  preferences = setTimeUnitPreference(preferences, 'min');

  assert.equal(saveUnitPreferences(storage, preferences), true);
  assert.deepEqual(loadUnitPreferences(storage), {
    version: UNIT_PREFERENCES_VERSION,
    valueUnits: { pressure: 'bar', temperature: 'F' },
    timeUnit: 'min',
  });
  assert.doesNotMatch(storage.value(UNIT_PREFERENCES_KEY), /values|samples|analysis/);
});

test('storage failures and malformed preference updates never throw or poison defaults', () => {
  const unavailable = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
  };

  assert.deepEqual(loadUnitPreferences(unavailable), defaults);
  assert.equal(saveUnitPreferences(unavailable, defaults), false);
  assert.deepEqual(setValueUnitPreference(defaults, '__proto__', 'bar'), defaults);
  assert.deepEqual(setTimeUnitPreference(defaults, ''), defaults);
});

test('backend dimensions map to the conservative display allowlist without gauge guesses', () => {
  assert.deepEqual(unitChoicesForDimension('pressure'), ['Pa', 'kPa', 'MPa', 'bar', 'psi']);
  assert.deepEqual(unitChoicesForDimension('temperature'), ['K', 'C', 'F']);
  assert.deepEqual(unitChoicesForDimension('time'), ['s', 'min', 'h']);
  assert.deepEqual(unitChoicesForDimension('unknown'), []);
  assert.equal(unitChoicesForDimension('pressure').includes('barg'), false);
  assert.equal(unitChoicesForDimension('pressure').includes('bara'), false);
});

test('preference updates reject unknown dimensions and cross-dimension units', () => {
  assert.deepEqual(setValueUnitPreference(defaults, 'pressure', 'h'), defaults);
  assert.deepEqual(setValueUnitPreference(defaults, 'mystery', 'bar'), defaults);
  assert.deepEqual(setTimeUnitPreference(defaults, 'bar'), defaults);
});

test('initial series view uses dimension preferences but leaves arithmetic to the backend', () => {
  const preferences = {
    version: UNIT_PREFERENCES_VERSION,
    valueUnits: { pressure: 'psi', temperature: 'F' },
    timeUnit: 'min',
  };
  const view = preferredSeriesView(
    preferences,
    { dimension: 'pressure', source_unit: 'PA' },
    { dimension: 'time', source_unit: 's' },
  );

  assert.deepEqual(view, {
    value_unit: 'psi',
    time_unit: 'min',
    quantity_kind: 'point',
    range: { mode: 'full' },
  });
  assert.equal('values' in view, false);

  const unknown = preferredSeriesView(defaults, { dimension: null, source_unit: 'barg' }, { dimension: null, source_unit: 'fortnight' });
  assert.deepEqual(unknown, { quantity_kind: 'point', range: { mode: 'full' } });
});

test('accepted backend metadata persists only canonical approved emitted units', () => {
  const converted = acceptSeriesUnitPreferences(
    defaults,
    { status: 'converted', dimension: 'pressure', output_unit: 'bar' },
    { status: 'identity', dimension: 'time', output_unit: 'min' },
  );
  assert.deepEqual(converted, {
    version: UNIT_PREFERENCES_VERSION,
    valueUnits: { pressure: 'bar' },
    timeUnit: 'min',
  });

  const sourceOnly = acceptSeriesUnitPreferences(
    converted,
    { status: 'source_only', dimension: 'pressure', output_unit: 'psi' },
    { status: 'source_only', dimension: 'time', output_unit: 'h' },
  );
  assert.deepEqual(sourceOnly, converted, 'source-only responses cannot replace accepted preferences');

  const malformedBackend = acceptSeriesUnitPreferences(
    defaults,
    { status: 'converted', dimension: 'pressure', output_unit: 'bananas' },
    { status: 'converted', dimension: 'time', output_unit: 'fortnight' },
  );
  assert.deepEqual(malformedBackend, defaults);

  const unknownStatus = acceptSeriesUnitPreferences(
    defaults,
    { status: 'mystery', dimension: 'pressure', output_unit: 'bar' },
    { status: 'mystery', dimension: 'time', output_unit: 'min' },
  );
  assert.deepEqual(unknownStatus, defaults);
});

function discoveredSeries({
  valueUnit = 'bar',
  timeUnit = 'min',
  valueStatus = 'not_requested',
  timeStatus = 'not_requested',
  quantityKind = 'point',
  range = { mode: 'full' },
} = {}) {
  return {
    unit: valueUnit,
    time_unit: timeUnit,
    view: {
      value_conversion: { status: valueStatus, output_unit: valueUnit, quantity_kind: quantityKind },
      time_conversion: { status: timeStatus, output_unit: timeUnit, quantity_kind: 'point' },
      range,
    },
  };
}

test('discovery response is reusable only when emitted units, quantity kind, and full range match', () => {
  const preferred = { value_unit: 'bar', time_unit: 'min', quantity_kind: 'point', range: { mode: 'full' } };

  assert.equal(discoveryMatchesPreferredView(discoveredSeries(), preferred), true);
  assert.equal(discoveryMatchesPreferredView(discoveredSeries({ valueUnit: 'psi' }), preferred), false);
  assert.equal(discoveryMatchesPreferredView(discoveredSeries({ timeUnit: 's' }), preferred), false);
  assert.equal(discoveryMatchesPreferredView(discoveredSeries({ quantityKind: 'delta' }), preferred), false);
  assert.equal(discoveryMatchesPreferredView(discoveredSeries({ range: { mode: 'tail', fraction: 0.25 } }), preferred), false);
});

test('source-only discovery cannot satisfy an explicit unit target but can represent an omitted target', () => {
  const sourceOnly = discoveredSeries({ valueUnit: 'barg', timeUnit: 'fortnight', valueStatus: 'source_only', timeStatus: 'source_only' });

  assert.equal(discoveryMatchesPreferredView(sourceOnly, {
    value_unit: 'barg',
    time_unit: 'fortnight',
    quantity_kind: 'point',
    range: { mode: 'full' },
  }), false);
  assert.equal(discoveryMatchesPreferredView(sourceOnly, {
    quantity_kind: 'point',
    range: { mode: 'full' },
  }), true);
});
