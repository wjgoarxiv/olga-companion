// M7: the edit table's approval card says the valve schedule (or time series) goes away.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const change = (note) => ({
  row: { id: 'v1', target: 'VALVE-1', field: 'opening', ...(note ? { note } : {}) },
  before: '1',
  after: '0.4',
});

test('a valve with a schedule shows the removal note with the new value', () => {
  assert.match(r.renderReviewedChange('en', change('schedule')), /<span class="case-edit-review-note" role="note">The opening schedule is removed: the valve stays at 0\.4 for the whole run\.<\/span>/);
  assert.match(r.renderReviewedChange('ko', change('schedule')), /class="case-edit-review-note" role="note">[^<]*0\.4/);
});

test('a time series row shows the series note in both languages', () => {
  for (const locale of ['en', 'ko']) {
    const html = r.renderReviewedChange(locale, change('series'));
    assert.match(html, /class="case-edit-review-note" role="note">[^<]*0\.4/, locale);
    assert.doesNotMatch(html, /caseEdit\.reviewNote/, locale);
  }
});

test('a plain change has no note', () => {
  const html = r.renderReviewedChange('en', change(null));
  assert.doesNotMatch(html, /case-edit-review-note/);
  assert.match(html, /VALVE-1 Valve opening/);
});
