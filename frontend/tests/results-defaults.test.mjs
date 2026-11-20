import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

import {
  DEFAULT_VALUE_UNITS,
  UNIT_PREFERENCES_VERSION,
  discoveryMatchesPreferredView,
  preferredSeriesView,
} from '../src/unitPreferences.mjs';

/* Plan v0111 item 10: the results screen opens on what an engineer reads first.
 * (1) Pressure shows in bar until the user picks another unit.
 * (2) Run id and output digest move into a collapsed details element. */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const none = { version: UNIT_PREFERENCES_VERSION, valueUnits: {}, timeUnit: null };
const seconds = { dimension: 'time', source_unit: 's' };

test('with no stored pressure choice the initial view asks for bar', () => {
  assert.equal(DEFAULT_VALUE_UNITS.pressure, 'bar');
  for (const source of ['PA', 'Pa', 'psi', 'bar']) {
    const view = preferredSeriesView(none, { dimension: 'pressure', source_unit: source }, seconds);
    assert.equal(view.value_unit, 'bar', `source ${source} defaults to bar`);
  }
  assert.equal('values' in preferredSeriesView(none, { dimension: 'pressure', source_unit: 'PA' }, seconds), false);
});

test('a stored user choice still wins over the bar default, including Pa', () => {
  for (const unit of ['Pa', 'psi', 'kPa']) {
    const stored = { ...none, valueUnits: { pressure: unit } };
    const view = preferredSeriesView(stored, { dimension: 'pressure', source_unit: 'PA' }, seconds);
    assert.equal(view.value_unit, unit);
  }
});

test('the bar default touches pressure only and never guesses a gauge unit', () => {
  const temp = preferredSeriesView(none, { dimension: 'temperature', source_unit: 'C' }, seconds);
  assert.equal(temp.value_unit, 'C', 'other dimensions keep the source unit');
  const gauge = preferredSeriesView(none, { dimension: 'pressure', source_unit: 'barg' }, seconds);
  assert.equal('value_unit' in gauge, false, 'an unconvertible pressure source stays as written');
  const unknown = preferredSeriesView(none, { dimension: null, source_unit: 'bar' }, seconds);
  assert.equal('value_unit' in unknown, false);
});

test('a source-only series cannot claim to satisfy the bar default', () => {
  const view = preferredSeriesView(none, { dimension: 'pressure', source_unit: 'PA' }, seconds);
  const sourceOnly = {
    unit: 'PA',
    time_unit: 's',
    view: {
      value_conversion: { status: 'source_only', output_unit: 'PA', quantity_kind: 'point' },
      time_conversion: { status: 'identity', output_unit: 's' },
      range: { mode: 'full' },
    },
  };
  assert.equal(discoveryMatchesPreferredView(sourceOnly, view), false);
});

test('the results header keeps run state first and folds run id and digest into details', async () => {
  const meta = await read('../src/ResultReceiptMeta.tsx');
  assert.match(meta, /<details className="result-lineage-details">/);
  assert.match(meta, /<summary>\{t\('results\.metaDetails'\)\}<\/summary>/);
  const open = meta.indexOf('<details');
  const close = meta.indexOf('</details>');
  assert.ok(open > 0 && close > open, 'the details element is closed in the same component');
  const inside = meta.slice(open, close);
  const outside = meta.slice(0, open);
  assert.match(inside, /results\.metaRun'/, 'run id lives in details');
  assert.match(inside, /results\.metaDigest/, 'output digest lives in details');
  assert.match(outside, /results\.metaStatus/, 'run state stays in the lead');
  assert.match(outside, /results\.metaModified/);
  assert.doesNotMatch(outside, /results\.metaRun'|results\.metaDigest'/);
  assert.equal(meta.slice(close).includes('<span>'), false, 'details is the last thing in the header');
  assert.doesNotMatch(meta, /<details[^>]*\bopen\b/, 'collapsed by default');
});

test('the layout still places the receipt meta after the case name', async () => {
  const layout = await read('../src/ResultsLayout.tsx');
  assert.ok(layout.indexOf('ws-canvas-name') < layout.indexOf('<ResultReceiptMeta'));
});

test('the details styling follows terminalcore: tokens, radius 0, 44px target, 12px floor', async () => {
  const css = await read('../src/styles/results.css');
  const rules = css.split('\n').filter((line) => line.includes('.result-lineage-details'));
  assert.ok(rules.length >= 2, 'details and summary have rules');
  const joined = rules.join('\n');
  assert.match(joined, /summary[^{]*\{[^}]*min-height:\s*44px/);
  assert.match(joined, /summary:focus-visible/);
  assert.doesNotMatch(joined, /border-radius:\s*[1-9]/, 'no rounded corners');
  assert.doesNotMatch(joined, /#[0-9a-f]{3,8}\b|rgb\(|font-size:\s*\d+px/i, 'tokens only');
  assert.doesNotMatch(joined, /animation|transition/, 'no motion needed to open a details element');
});

test('the details label is translated in both locales with matching keys', async () => {
  for (const locale of ['ko', 'en']) {
    assert.match(await read(`../src/i18n/${locale}.ts`), /'results\.metaDetails': '[^']+'/);
  }
  assert.doesNotMatch(await read('../src/i18n/ko.ts'), /'results\.metaDetails': '[^']*케이스/);
});
