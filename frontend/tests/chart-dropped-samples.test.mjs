// R3: the chart says how many NaN or empty samples were left out.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const conversion = (unit, dimension) => ({ status: 'converted', source_unit: unit, output_unit: unit, dimension });
const series = (dropped) => ({
  unit: 'bar',
  time_unit: 's',
  view: {
    value_conversion: conversion('bar', 'pressure'),
    time_conversion: conversion('s', 'time'),
    range: { mode: 'full' },
    ...(dropped === undefined ? {} : { dropped_non_finite: dropped }),
  },
});

test('the unit bar shows the dropped sample count in English and Korean', () => {
  assert.match(r.renderUnitBar('en', series(3)), /<p class="chart-unit-note" role="note">3 samples without a number \(NaN or empty\) are left out/);
  assert.match(r.renderUnitBar('ko', series(3)), /<p class="chart-unit-note" role="note">숫자가 없는 샘플 3개/);
});

test('no note when nothing was dropped or the field is missing', () => {
  assert.doesNotMatch(r.renderUnitBar('en', series(0)), /chart-unit-note/);
  assert.doesNotMatch(r.renderUnitBar('en', series(undefined)), /chart-unit-note/);
});
