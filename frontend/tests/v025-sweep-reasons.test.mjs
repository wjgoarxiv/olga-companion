// 0.1.25 row 3: an empty sweep cell, or a cell with no change, says why in the UI language.
// The backend's English sentence is kept only as the hover detail.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { sweepReasonText } from '../src/sweepSummaryModel.mjs';
import { translate } from '../src/i18n/index.ts';

const HANGUL = /[가-힣]/;
const CODES = ['no_run', 'start_failed', 'run_missing', 'run_not_completed', 'no_tpl', 'not_available', 'empty_series', 'no_value', 'base_no_value', 'unit_differs'];
const t = (locale) => (key, vars) => translate(locale, key, vars);

test('every reason code has Korean and English text', () => {
  for (const code of CODES) {
    const ko = sweepReasonText(code, t('ko'));
    const en = sweepReasonText(code, t('en'));
    assert.ok(HANGUL.test(ko), `${code} ko: ${ko}`);
    assert.ok(en && !HANGUL.test(en) && en !== `sweep.reason.${code}`, `${code} en: ${en}`);
  }
});

test('an unknown or missing code falls back to "no value"', () => {
  assert.equal(sweepReasonText('something_new', t('ko')), translate('ko', 'sweep.noValue'));
  assert.equal(sweepReasonText(null, t('en')), translate('en', 'sweep.noValue'));
  assert.equal(sweepReasonText(undefined, t('ko')), translate('ko', 'sweep.noValue'));
});

test('a cell with no specific reason is read as "no value" once, not twice (review finding 2)', async () => {
  const { reviewNotesRenderer } = await import('./helpers/render-review-notes.mjs');
  const r = await reviewNotesRenderer();
  for (const reasonCell of [{ reason: 'no value', reason_code: 'no_value' }, { reason: null, reason_code: null }, { reason: 'odd', reason_code: 'new_code' }]) {
    const rows = [{ index: 0, params: [], run_id: 'r0', state: 'completed', ok: true, tpl: null, outputs: { PT: { value: null, unit: null, time: null, time_unit: null, ...reasonCell } } }];
    const ko = r.renderSweepSummary('ko', rows);
    assert.match(ko, /<span class="ui-visually-hidden">값 없음<\/span>/, JSON.stringify(reasonCell));
    assert.doesNotMatch(ko, /값 없음: 값/);
    const en = r.renderSweepSummary('en', rows);
    assert.match(en, /<span class="ui-visually-hidden">no value<\/span>/);
  }
});

test('the table shows the translated reason, and the backend text only as the hover detail', () => {
  const table = readFileSync(new URL('../src/SweepSummaryTable.tsx', import.meta.url), 'utf8');
  assert.match(table, /sweepReasonText\(cell\?\.reason_code, t\)/);
  assert.match(table, /sweepReasonText\(cell\.change_reason_code, t\)/);
  assert.doesNotMatch(table, /title=\{cell\?\.reason \?\?/);
  assert.doesNotMatch(table, /title=\{cell\.change_reason\}/);
  assert.doesNotMatch(table, /: \{cell\.change_reason\}<\/span>/);
  const api = readFileSync(new URL('../src/sweepApi.ts', import.meta.url), 'utf8');
  assert.match(api, /reason_code\?: string \| null;/);
  assert.match(api, /change_reason_code\?: string \| null;/);
});
