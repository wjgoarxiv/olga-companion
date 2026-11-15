import assert from 'node:assert/strict';
import test from 'node:test';
import * as resultPresentation from '../src/resultPresentation.ts';
import { figuresForSpan, formatSignificant } from '../src/significantFigures.mjs';

// A 5 m air-water line on 2026-11-10: inlet PT moved between 101,325 and 101,650 Pa.
// At 3 significant figures every value read 102,000, which hid the ~300 Pa drop.
const pressure = {
  variable: 'PT',
  units: { time: 's', value: 'Pa' },
  position: 'POS_MAIN_1',
  total_rows: 61,
  returned_rows: 2,
  rows: [
    { time: 118, value: 101629.3 },
    { time: 120, value: 101629.3 },
  ],
  truncated: true,
  truncation: 'tail',
  analysis: { minimum: 101325, maximum: 101650, mean: 101627.4 },
};

test('a narrow span raises the figures so the span stays readable', () => {
  assert.equal(figuresForSpan(101325, 101650, 3), 5);
  assert.notEqual(formatSignificant(101629.3, figuresForSpan(101325, 101650, 3)), '102,000');
});

test('a wide or flat span keeps the chosen figures', () => {
  assert.equal(figuresForSpan(1.25, 2.25, 3), 3);
  assert.equal(figuresForSpan(5, 5, 4), 4);
  assert.equal(figuresForSpan(0, 0, 5), 5);
});

test('a very long series without an analysis block still yields figures', () => {
  const rows = Array.from({ length: 300_000 }, (_, index) => ({ time: index, value: 101325 + (index % 300) }));
  assert.equal(resultPresentation.seriesFigures({ rows }, 3), 5);
});

test('the series summary and rows use the raised figures at a 3-figure setting', () => {
  const table = resultPresentation.presentSeriesTable(pressure, 3);
  assert.equal(table.analysis_summary, 'Min 101,330 · Max 101,650 · Mean 101,630');
  assert.equal(resultPresentation.seriesFigures(pressure, 3), 5);
});
