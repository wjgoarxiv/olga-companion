// 0.1.22 row 2: series in different units get their own panel on one time axis, so a 0–1 controller
// output is not flattened next to a pressure in bar (0.1.21 PVT).
import test from 'node:test';
import assert from 'node:assert/strict';
import { sharedTimeSpan, trendPanels } from '../src/trendPanels.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const item = (key, unit, time = [0, 10, 20], values = [1, 2, 3]) => ({
  key, color: '#000', series: { variable: key, unit, time_unit: 's', time, values },
});

test('one panel per unit, the active series first, same-unit series kept together', () => {
  const plotted = [item('PT_A', 'bar'), item('CONTR', '-'), item('PT_B', 'bar')];
  const panels = trendPanels(plotted, 'CONTR', false);
  assert.deepEqual(panels.map((p) => [p.primary.key, p.overlays.map((o) => o.key)]), [
    ['CONTR', []],
    ['PT_A', ['PT_B']],
  ]);
});

test('a single series, or every series in one unit, is one panel as before', () => {
  assert.equal(trendPanels([item('PT', 'bar')], 'PT', false).length, 1);
  const same = trendPanels([item('PT_A', 'bar'), item('PT_B', 'bar')], 'PT_B', false);
  assert.deepEqual(same.map((p) => [p.primary.key, p.overlays.map((o) => o.key)]), [['PT_B', ['PT_A']]]);
});

test('the one-axis toggle puts every series on the active axis, as before 0.1.22', () => {
  const plotted = [item('PT', 'bar'), item('CONTR', '-')];
  const panels = trendPanels(plotted, 'PT', true);
  assert.deepEqual(panels.map((p) => [p.primary.key, p.overlays.map((o) => o.key)]), [['PT', ['CONTR']]]);
});

test('no active series means no panels', () => {
  assert.deepEqual(trendPanels([item('PT', 'bar')], 'missing', false), []);
});

test('every panel shares the time span of all plotted series', () => {
  const plotted = [item('PT', 'bar', [5, 10]), item('CONTR', '-', [0, 60])];
  assert.deepEqual(sharedTimeSpan(plotted), [0, 60]);
  assert.equal(sharedTimeSpan([item('X', 'bar', [Number.NaN], [1])]), null);
});

test('a chart given the shared span and a hover time from its neighbour shows that time', async () => {
  const r = await reviewNotesRenderer();
  const series = { path: 'a.tpl', variable: 'CONTR', position: 'PC', unit: '-', time_unit: 's', description: '', time: [0, 10, 20], values: [0.3, 0.1, 0] };
  const html = r.renderTrendChartSynced(series, [0, 60], 10);
  assert.match(html, /class="trend-readout"/, 'the readout follows the hover time of the other panel');
  assert.match(html, />60</, 'the time axis reaches the shared end');
  assert.doesNotMatch(r.renderTrendChartSynced(series, [0, 60], null), /class="trend-readout"/);
});

test('PVT D7: stacked panels each keep a readable height instead of sharing one chart height', async () => {
  const { readFile } = await import('node:fs/promises');
  const css = await readFile(new URL('../src/styles/results.css', import.meta.url), 'utf8');
  assert.match(css, /\.rv-chart-wrap:has\(> \.rv-chart-panel \+ \.rv-chart-panel\) \{[^}]*height: auto;/);
  assert.match(css, /\.rv-chart-wrap:has\(> \.rv-chart-panel \+ \.rv-chart-panel\) > \.rv-chart-panel \{[^}]*min-height: 260px;/);
});

test('review R8: two stacked panels with the same sample count never share an element id', async () => {
  const r = await reviewNotesRenderer();
  const series = { path: 'a.tpl', variable: 'PT', position: 'IN', unit: '-', time_unit: 's', description: '', time: [0, 10, 20], values: [1, 2, 3] };
  const ids = [...r.renderTwoTrendCharts(series).matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(ids.length >= 4, 'each panel names its title and description');
  assert.equal(new Set(ids).size, ids.length, `duplicate ids: ${ids.join(', ')}`);
});
