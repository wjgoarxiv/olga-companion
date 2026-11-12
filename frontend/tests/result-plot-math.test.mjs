import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyBrushDomain,
  clientToDataX,
  fitViewBoxLetterbox,
  niceTicks,
  pickAutoPlotVariable,
} from '../src/trendGeometry.mjs';
import { formatUnit } from '../src/formatUnit.mjs';

test('nice ticks land on 1/2/2.5/5 steps inside the data range', () => {
  assert.deepEqual(niceTicks(0, 97, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(niceTicks(3.2, 3.8, 4), [3.2, 3.4, 3.6, 3.8]);
  for (const [low, high, count] of [[-50, 50, 5], [0, 97, 5], [3.2, 3.8, 4]]) {
    const ticks = niceTicks(low, high, count);
    assert.ok(ticks[0] <= low && ticks[ticks.length - 1] >= high, 'ticks cover the range');
    const step = ticks[1] - ticks[0];
    const family = step / (10 ** Math.floor(Math.log10(step)));
    assert.ok([1, 2, 2.5, 5, 10].some((nice) => Math.abs(nice - family) < 1e-9), `step ${step} is nice`);
  }
});

test('nice ticks collapse gracefully for degenerate ranges', () => {
  assert.deepEqual(niceTicks(5, 5, 5), [5]);
  assert.deepEqual(niceTicks(0, 0.001, 4).length >= 2, true);
  assert.deepEqual(niceTicks(Number.NaN, 10, 5), []);
  const ticks = niceTicks(0, 3600, 6);
  assert.ok(ticks[0] <= 0 && ticks[ticks.length - 1] >= 3600, 'ticks cover the range');
  for (let index = 1; index < ticks.length; index += 1) {
    assert.ok(ticks[index] > ticks[index - 1], 'ticks ascend');
  }
});

test('brush domains keep the inclusive window in order', () => {
  const time = [0, 10, 20, 30, 40];
  const values = [1, 2, 3, 4, 5];
  assert.deepEqual(applyBrushDomain(time, values, 10, 30), { time: [10, 20, 30], values: [2, 3, 4] });
  assert.deepEqual(applyBrushDomain(time, values, 30, 10), { time: [10, 20, 30], values: [2, 3, 4] }, 'reversed drag still selects');
  assert.deepEqual(applyBrushDomain(time, values, 5, 5), { time: [], values: [] }, 'empty drag selects nothing');
});

test('auto-plot prefers the first pressure variable, else the first variable', () => {
  const pressure = { variable: 'PT', position: 'PIPE-1' };
  const other = { variable: 'HOL', position: 'PIPE-1' };
  assert.equal(pickAutoPlotVariable([other, pressure]), pressure);
  assert.equal(pickAutoPlotVariable([other]), other);
  assert.equal(pickAutoPlotVariable([]), null);
});

test('display units keep canonical casing with display-only overrides', () => {
  assert.equal(formatUnit('bara'), 'bara');
  assert.equal(formatUnit('C'), '°C');
  assert.equal(formatUnit('dimensionless'), '-');
  assert.equal(formatUnit('Pa'), 'Pa');
});

test('letterboxed svg maps pointer x through the drawn plot area only', () => {
  // Exact aspect: gutters sit at the rect edges.
  const exact = { left: 0, width: 640, height: 400, min: 0, max: 3600 };
  assert.equal(clientToDataX(76, exact.left, exact.width, exact.height, exact.min, exact.max), 0);
  assert.equal(clientToDataX(616, exact.left, exact.width, exact.height, exact.min, exact.max), 3600);
  assert.equal(clientToDataX(346, exact.left, exact.width, exact.height, exact.min, exact.max), 1800);
  // Tall rect: content is 640x400 centred vertically, x mapping unchanged.
  assert.equal(clientToDataX(76, 0, 640, 800, 0, 3600), 0);
  assert.equal(clientToDataX(616, 0, 640, 800, 0, 3600), 3600);
  // Wide rect: 640x400 centred horizontally, gutters shift by the offset.
  const fit = fitViewBoxLetterbox(1000, 400, 640, 400);
  assert.equal(fit.offsetX, 180);
  assert.equal(clientToDataX(180 + 76, 0, 1000, 400, 0, 3600), 0);
  assert.equal(clientToDataX(180 + 616, 0, 1000, 400, 0, 3600), 3600);
  // Outside the plot area clamps instead of extrapolating.
  assert.equal(clientToDataX(-50, 0, 640, 400, 0, 3600), 0);
  assert.equal(clientToDataX(9999, 0, 640, 400, 0, 3600), 3600);
});

test('series table windows keep spacers exact', async () => {
  const { seriesTableWindow } = await import('../src/resultPresentation.ts');
  assert.deepEqual(seriesTableWindow(0, 0, 300), { start: 0, end: 0, topSpacer: 0, bottomSpacer: 0 });
  const first = seriesTableWindow(1000, 0, 300, 30, 2);
  assert.equal(first.start, 0);
  assert.equal(first.topSpacer + (first.end - first.start) * 30 + first.bottomSpacer, 1000 * 30);
  const mid = seriesTableWindow(1000, 900, 300, 30, 2);
  assert.ok(mid.start > 0 && mid.end > mid.start, 'the window moves with scroll');
  assert.equal(mid.topSpacer, mid.start * 30);
  assert.equal(mid.topSpacer + (mid.end - mid.start) * 30 + mid.bottomSpacer, 1000 * 30);
  const tail = seriesTableWindow(1000, 100000, 300, 30, 2);
  assert.equal(tail.end, 1000);
  assert.equal(tail.bottomSpacer, 0);
});
