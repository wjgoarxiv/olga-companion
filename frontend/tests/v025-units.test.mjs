// 0.1.25 row 1: the calibration rail shows display units (Pa, not PA), and a glossary popup gives
// its unit in the UI language ("길이 단위", not "length").
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { glossaryUnitKey } from '../src/glossary.ts';
import { formatUnit } from '../src/formatUnit.mjs';
import { translate } from '../src/i18n/index.ts';

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');
const entries = JSON.parse(readFileSync(new URL('../../src/olga_companion/resources/olga_glossary.json', import.meta.url), 'utf8'));
const HANGUL = /[가-힣]/;
const unitLabel = (unit, locale) => {
  const key = glossaryUnitKey(unit);
  return key ? translate(locale, key) : formatUnit(unit);
};

test('the calibration rail prints both source units through formatUnit', () => {
  const rail = src('CalibrationRail.tsx');
  assert.match(rail, /formatUnit\(valueConversion\.source_unit\)/);
  assert.match(rail, /formatUnit\(timeConversion\.source_unit\)/);
  assert.doesNotMatch(rail, /\{valueConversion\.source_unit \|\|/);
});

test('a locked axis unit in the unit bar shows its display label; the option value stays the raw unit (review finding 3)', () => {
  const bar = src('ChartUnitBar.tsx');
  assert.match(bar, /t\('calib\.sourceLocked', \{ unit: formatUnit\(valueUnit\) \}\)/);
  assert.match(bar, /t\('calib\.sourceLocked', \{ unit: formatUnit\(timeUnit\) \}\)/);
  assert.match(bar, /<option value=\{valueSelected \?\? valueUnit\}>/);
  assert.match(bar, /<option value=\{timeSelected \?\? timeUnit\}>/);
});

test('every glossary unit reads in Korean, or is a unit symbol', () => {
  const units = [...new Set(entries.map((entry) => entry.unit).filter(Boolean))];
  assert.ok(units.length >= 10);
  for (const unit of units) {
    const ko = unitLabel(unit, 'ko');
    assert.ok(HANGUL.test(ko) || !/[a-z]{4,}/i.test(ko), `${unit} -> ${ko}`);
  }
});

test('the English popup keeps the English unit words; a raw code shows as its symbol', () => {
  assert.equal(unitLabel('length', 'en'), 'length');
  assert.equal(unitLabel('heat capacity unit', 'en'), 'heat capacity unit');
  assert.equal(unitLabel('length', 'ko'), '길이 단위');
  assert.equal(unitLabel('PA', 'ko'), 'Pa');
  assert.equal(unitLabel('kg/s', 'ko'), 'kg/s');
});

test('the glossary popup shows the translated unit', () => {
  const term = src('GlossaryTerm.tsx');
  assert.match(term, /glossaryUnitKey\(/);
  assert.match(term, /formatUnit\(/);
  assert.doesNotMatch(term, /\$\{entry\.unit\}/);
  assert.match(term, /<span>\{meaning\}\{unitText\}<\/span>/);
});
