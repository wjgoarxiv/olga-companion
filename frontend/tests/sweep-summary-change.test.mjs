// 0.1.20 row 8: each sweep case shows its change from the base case and the table sorts by it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { sortSummaryRows, formatChange } from '../src/sweepSummaryModel.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const cell = (value, change, reason = null) => ({ value, unit: 'bara', time: 60, time_unit: 's', reason: value == null ? reason : null, change, change_reason: change == null ? reason : null });
const blank = (reason) => ({ PT: cell(null, null, reason), TM: cell(null, null, reason), HOL: cell(null, null, reason), LIQC: cell(null, null, reason) });
const row = (index, pt, change, ok = true) => ({
  index, params: [{ path: 'SOURCE.MASSFLOW', value: `${index} kg/s` }], run_id: `r${index}`, state: ok ? 'completed' : 'failed', ok, tpl: null,
  outputs: ok ? { ...blank('HOL series is empty'), PT: cell(pt, change) } : blank('run failed'),
});
const rows = [row(0, 100, 0), row(1, 130, 30), row(2, 90, -10), row(3, null, null, false)];

test('sorting by a change puts the largest change first and cases without one last', () => {
  assert.deepEqual(sortSummaryRows(rows, 'case').map((x) => x.index), [0, 1, 2, 3]);
  assert.deepEqual(sortSummaryRows(rows, 'PT').map((x) => x.index), [1, 2, 0, 3]);
  assert.deepEqual(rows.map((x) => x.index), [0, 1, 2, 3], 'the input is not reordered');
});

test('a change is signed with its unit; the base and a missing change say so', () => {
  assert.equal(formatChange(rows[1].outputs.PT, false), '+30 bara');
  assert.equal(formatChange(rows[2].outputs.PT, false), '−10 bara');
  assert.equal(formatChange(rows[0].outputs.PT, true), null);
  assert.equal(formatChange(rows[3].outputs.PT, false), null);
});

test('the table shows the change line, the base label and a sort choice in en and ko', () => {
  const en = r.renderSweepSummary('en', rows, 'PT');
  assert.match(en, /\+30 bara/);
  assert.match(en, />Base case</);
  assert.match(en, /Sort by/);
  assert.ok(en.indexOf('+30 bara') < en.indexOf('−10 bara'), 'sorted by the PT change');
  assert.match(en, /title="run failed"/, 'a failed case shows — with the reason');
  const ko = r.renderSweepSummary('ko', rows, 'case');
  assert.match(ko, />기준 사례</);
  assert.match(ko, /정렬/);
});

test('a missing value says why to a screen reader, not only in a tooltip, and nothing is announced before a sort', () => {
  const html = r.renderSweepSummary('en', rows, 'case');
  assert.match(html, /<span class="ui-visually-hidden">no value: run failed<\/span>/);
  assert.match(html, /<span class="ui-visually-hidden">no value: HOL series is empty<\/span>/);
  assert.match(html, /<p class="ui-visually-hidden" role="status"><\/p>/);
});
