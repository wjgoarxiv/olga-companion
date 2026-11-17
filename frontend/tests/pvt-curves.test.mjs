import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { buildCurveChart, buildEnvelopeChart, hasEnvelope, lineStyle, pickRows, MAX_CURVE_LINES } from '../src/pvtCurves.ts';

test('at most seven pressures are drawn, evenly spaced, keeping the first and last', () => {
  assert.deepEqual(pickRows(3), [0, 1, 2]);
  assert.deepEqual(pickRows(0), []);
  const picked = pickRows(64);
  assert.equal(picked.length, MAX_CURVE_LINES);
  assert.equal(picked[0], 0);
  assert.equal(picked.at(-1), 63);
  assert.deepEqual(picked, [...picked].sort((a, b) => a - b));
});

test('colour is never the only channel: the lines after the fourth are dashed', () => {
  assert.deepEqual([0, 1, 2, 3].map((i) => lineStyle(i).dash), ['', '', '', '']);
  const later = [4, 5, 6].map((i) => lineStyle(i).dash);
  assert.ok(later.every((dash) => dash !== ''));
  assert.equal(new Set(later).size, 3);
  assert.equal(lineStyle(0).colorVar, '--pipe-1');
  assert.equal(lineStyle(6).colorVar, '--pipe-7');
});

test('a curve chart draws one polyline per picked pressure and breaks the line at a gap', () => {
  const chart = buildCurveChart([1e5, 1e7], [5, 40, 80], [[1, null, 3], [10, 20, 30]]);
  assert.equal(chart.lines.length, 2);
  assert.equal(chart.lines[0].d.match(/M/g).length, 2);
  assert.equal(chart.lines[0].points, 2);
  assert.equal(chart.lines[1].d.match(/M/g).length, 1);
  assert.equal(chart.lines[1].pressurePa, 1e7);
  const { plot } = chart;
  for (const [x, y] of chart.lines.flatMap((l) => [...l.d.matchAll(/[ML]([\d.-]+) ([\d.-]+)/g)].map((m) => [+m[1], +m[2]]))) {
    assert.ok(x >= plot.left && x <= plot.right && y >= plot.top && y <= plot.bottom);
  }
  assert.ok(chart.xTicks.length >= 2 && chart.yTicks.length >= 2);
});

test('a flat or empty property does not divide by zero', () => {
  const flat = buildCurveChart([1e5], [5, 40], [[7, 7]]);
  assert.ok(!flat.lines[0].d.includes('NaN'));
  const empty = buildCurveChart([1e5], [5, 40], [[null, null]]);
  assert.equal(empty.lines[0].points, 0);
  assert.ok(!empty.lines[0].d.includes('NaN'));
});

test('the envelope chart plots bubble, dew and the critical point in bar and °C', () => {
  const envelope = {
    bubble: [[1e5, -56.5], [1e6, -40], [7.38e6, 31]],
    dew: [[1e5, -78], [7.38e6, 31]],
    critical: { p_pa: 7.38e6, t_c: 31 },
  };
  assert.equal(hasEnvelope(envelope), true);
  const chart = buildEnvelopeChart(envelope);
  assert.match(chart.bubble, /^M/);
  assert.match(chart.dew, /^M/);
  // the critical point is the top-right corner of the data, so it lies on the plot edge
  assert.equal(chart.critical.x, chart.plot.right);
  assert.equal(chart.critical.y, chart.plot.top);
  assert.ok(chart.yTicks.every((tick) => Number.isFinite(tick.pos)));
});

test('an envelope with nothing usable is not shown', () => {
  assert.equal(hasEnvelope(undefined), false);
  assert.equal(hasEnvelope({ bubble: [], dew: [], critical: null }), false);
  assert.equal(hasEnvelope({ bubble: [[1, null], [null, 2]], dew: [], critical: null }), false);
  assert.equal(hasEnvelope({ bubble: [], dew: [], critical: { p_pa: 1e6, t_c: 10 } }), true);
  const gap = buildEnvelopeChart({ bubble: [[1e5, 0], [null, null], [1e6, 20]], dew: [], critical: null });
  assert.equal(gap.bubble.match(/M/g).length, 2);
});

test('the preview wires a roving tablist, the curve and envelope svgs and the legacy table', async () => {
  const view = await readFile(new URL('../src/PvtGridPreview.tsx', import.meta.url), 'utf8');
  assert.match(view, /<Tabs\b/);
  assert.match(view, /buildCurveChart\(/);
  assert.match(view, /buildEnvelopeChart\(/);
  assert.match(view, /role="img"[\s\S]*?<title[\s\S]*?<desc/);
  assert.match(view, /grid\.points/);
  assert.match(view, /pvtGrid\.legacyNoTemperature/);
  const tabs = await readFile(new URL('../src/ui/Tabs.tsx', import.meta.url), 'utf8');
  assert.match(tabs, /role="tablist"[\s\S]*tabIndex=\{index === selected \? 0 : -1\}/);
});

test('the curve styles use design tokens only, keep text readable and do not animate', async () => {
  const css = (await readFile(new URL('../src/styles/workspace.css', import.meta.url), 'utf8'));
  const block = css.slice(css.indexOf('/* PVT curves'));
  assert.ok(block.length > 100, 'curve rules are appended after the .pvt-grid section');
  assert.doesNotMatch(block, /animation|transition/);
  assert.doesNotMatch(block, /#[0-9a-fA-F]{3,6}\b/);
  assert.doesNotMatch(block, /font-size:\s*\d+px/);
  assert.match(block, /\.pvt-curve-line/);
});
