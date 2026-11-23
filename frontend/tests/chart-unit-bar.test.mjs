import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

/* Owner request 2026-11-16: graph units should be easy to change, in a natural
 * place. The chart had no axis units at all and the unit selects sat in a
 * separate rail below it. Units now sit on a bar directly above the chart:
 * the y-axis variable with its unit on the left, time with its unit on the right. */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the plot tab puts the unit bar directly above the chart', async () => {
  const plot = await read('../src/ResultPlotTab.tsx');
  assert.match(plot, /<ChartUnitBar[\s\S]*?\/>\s*<TrendChart/, 'the bar comes right before the chart');
  assert.match(plot, /valueLabel=\{overlay\.activeVariable\?\.variable/);
});

test('the bar offers value and time units from the dimension catalog', async () => {
  const bar = await read('../src/ChartUnitBar.tsx');
  assert.match(bar, /unitChoicesForDimension\(valueConversion\.dimension\)/);
  assert.match(bar, /unitChoicesForDimension\('time'\)/);
  assert.match(bar, /onChange\(\{ \.\.\.view, value_unit: event\.target\.value \}\)/);
  assert.match(bar, /onChange\(\{ \.\.\.view, time_unit: event\.target\.value \}\)/);
  assert.match(bar, /className="chart-unit chart-unit-y"/);
  assert.match(bar, /className="chart-unit chart-unit-x"/);
});

test('the rail no longer repeats the unit selects', async () => {
  const rail = await read('../src/CalibrationRail.tsx');
  assert.doesNotMatch(rail, /<select/);
  assert.doesNotMatch(rail, /value_unit|time_unit/);
});

test('unit selects are 44 px touch targets on narrow screens', async () => {
  const css = await read('../src/styles/results.css');
  assert.match(css, /\.chart-unit-bar\s*\{[^}]*justify-content:\s*space-between/);
  const mobile = css.slice(css.indexOf('@media (max-width: 760px)'));
  assert.match(mobile, /\.chart-unit select\s*\{[^}]*min-height:\s*44px/);
});

test('the bar label is translated', async () => {
  for (const locale of ['ko', 'en']) {
    assert.match(await read(`../src/i18n/${locale}.ts`), /'chartUnits\.aria': '/);
  }
});

/* Live PVT 2026-11-16: OLGA writes "PA" and "°C". A select whose value is not one of
 * its options shows the first option, so the bar must match the catalog spelling. */
test('the bar shows the catalog spelling of the current unit', async () => {
  const { matchUnitChoice } = await import('../src/unitPreferences.mjs');
  assert.equal(matchUnitChoice(['Pa', 'kPa'], 'PA'), 'Pa');
  assert.equal(matchUnitChoice(['K', 'C', 'F'], '°C'), 'C');
  assert.equal(matchUnitChoice(['K', 'C', 'F'], 'degF'), 'F');
  assert.equal(matchUnitChoice(['s', 'min'], 'weird'), null);
  const bar = await read('../src/ChartUnitBar.tsx');
  assert.match(bar, /matchUnitChoice\(valueChoices, valueUnit\)/);
  assert.match(bar, /matchUnitChoice\(timeChoices, timeUnit\)/);
});

/* Live PVT 2026-11-16: after switching to bar and min the readout still said
 * "t=28.844316666666668 s · 10.4 Pa": the source unit won over the converted one,
 * the time unit was hard-coded and the time was not rounded. */
test('the readout speaks the converted units and rounds the time', async () => {
  const chart = await read('../src/TrendChart.tsx');
  assert.match(chart, /const shownUnit = series\.unit \|\| unit \|\| '';/);
  assert.match(chart, /time: metric\(readout\.time, significantFigures\)/);
  assert.match(chart, /timeUnit: formatUnit\(series\.time_unit \|\| 's'\)/);
  for (const locale of ['ko', 'en']) {
    assert.match(await read(`../src/i18n/${locale}.ts`), /'results\.readout': 't=\{time\} \{timeUnit\} · \{value\}'/);
  }
});
