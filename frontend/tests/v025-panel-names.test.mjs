// 0.1.25 row 2: a chart panel with one variable at two positions names each position
// ("PT · PIPE-1 3, PT · PIPE-1 9"), not "PT, PT". A name that appears once stays plain.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { panelSeriesNames } from '../src/trendPanels.mjs';

const item = (variable, position) => ({ key: `${variable}@${position}`, variable: { variable, position }, series: { unit: 'PA', time: [] } });

test('one variable at two positions gets the position in each name', () => {
  assert.equal(panelSeriesNames([item('PT', 'PIPE-1 3'), item('PT', 'PIPE-1 9')]), 'PT · PIPE-1 3, PT · PIPE-1 9');
});

test('names that appear once stay plain, also next to a repeated one', () => {
  assert.equal(panelSeriesNames([item('PT', 'A'), item('GT', 'A')]), 'PT, GT');
  assert.equal(panelSeriesNames([item('PT', 'A'), item('PT', 'B'), item('GT', 'A')]), 'PT · A, PT · B, GT');
  assert.equal(panelSeriesNames([item('PT', 'A')]), 'PT');
});

test('the same series from another run is named by its run, as the chips do (review finding 1)', () => {
  const other = { ...item('PT', 'PIPE-1 3'), key: 'other', source: 'run 2' };
  assert.equal(panelSeriesNames([item('PT', 'PIPE-1 3'), other]), 'PT · PIPE-1 3, PT · PIPE-1 3 · run 2');
  const otherElsewhere = { ...item('PT', 'PIPE-1 9'), key: 'other', source: 'run 2' };
  assert.equal(panelSeriesNames([item('PT', 'PIPE-1 3'), otherElsewhere]), 'PT · PIPE-1 3, PT · PIPE-1 9 · run 2');
});

test('a repeated name without a position stays plain', () => {
  assert.equal(panelSeriesNames([item('PT', ''), item('PT', undefined)]), 'PT, PT');
});

test('the chart stack uses it for the panel title and its accessible name', () => {
  const stack = readFileSync(new URL('../src/TrendChartStack.tsx', import.meta.url), 'utf8');
  assert.match(stack, /panelSeriesNames\(\[panel\.primary, \.\.\.panel\.overlays\]\)/);
  assert.doesNotMatch(stack, /item\.variable\.variable\)\.join/);
});
