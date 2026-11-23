// 0.1.26 hotfix (seen in the 0.1.25 PVT): the unit bar's choices read "C" instead of "°C", and the
// descriptive summary shows the direction word "decreasing" in English in the Korean UI.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { formatUnit } from '../src/formatUnit.mjs';
import { translate } from '../src/i18n/index.ts';

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('every unit choice in the unit bar is labelled through formatUnit; the option value stays raw', () => {
  const bar = src('ChartUnitBar.tsx');
  const choices = bar.match(/<option key=\{unit\} value=\{unit\}>\{formatUnit\(unit\)\}<\/option>/g) ?? [];
  assert.equal(choices.length, 2);
  assert.doesNotMatch(bar, /<option key=\{unit\} value=\{unit\}>\{unit\}<\/option>/);
  assert.equal(formatUnit('C'), '°C');
  assert.equal(formatUnit('F'), '°F');
  assert.equal(formatUnit('K'), 'K');
});

test('the descriptive summary translates the direction and formats the range unit', () => {
  const view = src('ResultAnalysis.tsx');
  assert.doesNotMatch(view, /<dd>\{series\.analysis\.direction\}<\/dd>/);
  assert.match(view, /directionLabel\(series\.analysis\.direction, t\)/);
  assert.match(view, /unit: formatUnit\(series\.unit \?\? ''\)/);
});

test('each direction has a ko and en label, and the Korean one is not English', () => {
  for (const dir of ['increasing', 'decreasing', 'stable']) {
    const key = `analysis.dir.${dir}`;
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.notEqual(ko, key, `ko ${key}`);
    assert.notEqual(en, key, `en ${key}`);
    assert.match(ko, /[가-힣]/, `ko ${key} is Korean`);
  }
});
