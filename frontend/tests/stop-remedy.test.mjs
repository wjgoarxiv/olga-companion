// 0.1.20 row 6: the stop card points at the edit-table row; it never fills a value or saves.
import test from 'node:test';
import assert from 'node:assert/strict';
import { openStopRemedy, REMEDY_REASONS } from '../src/stopRemedyModel.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();

function spy(answer) {
  const urls = [];
  const opened = [];
  return {
    urls, opened,
    deps: {
      get: async (url, init) => { urls.push([url, init?.method ?? 'GET']); return answer; },
      activeCase: 'case.genkey',
      open: (rel, rowId) => opened.push([rel, rowId]),
    },
  };
}

test('a row pointer opens the table at that row and only reads the server', async () => {
  const s = spy({ rel: 'cases/case.genkey', row_id: 'integration.max_dt_s', reason_key: 'row' });
  assert.deepEqual(await openStopRemedy('run 1', s.deps), { reasonKey: null });
  assert.deepEqual(s.opened, [['cases/case.genkey', 'integration.max_dt_s']]);
  assert.deepEqual(s.urls, [['/api/case-edit/remedy?run_id=run%201', 'GET']]);
  assert.ok(s.urls.every(([url]) => !url.includes('publish') && !url.includes('/plan')));
});

test('no row, a changed case or another active case opens nothing and gives a reason', async () => {
  for (const reason of ['table_range', 'unknown', 'sweep_only', 'fixed', 'not_editable', 'ambiguous', 'source_changed', 'outside_workspace']) {
    const s = spy({ rel: reason === 'outside_workspace' ? null : 'case.genkey', row_id: null, reason_key: reason });
    assert.deepEqual(await openStopRemedy('r', s.deps), { reasonKey: `run.stop.remedy.reason.${reason}` });
    assert.deepEqual(s.opened, []);
  }
  const other = spy({ rel: 'other.genkey', row_id: 'integration.end_time_s', reason_key: 'row' });
  assert.deepEqual(await openStopRemedy('r', other.deps), { reasonKey: 'run.stop.remedy.reason.not_active' });
  assert.deepEqual(other.opened, []);
  const odd = spy({ rel: 'case.genkey', row_id: null, reason_key: 'something_new' });
  assert.deepEqual(await openStopRemedy('r', odd.deps), { reasonKey: 'run.stop.remedy.reason.unknown' });
});

test('every reason has words in en and ko', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  for (const locale of ['en', 'ko']) {
    for (const reason of [...REMEDY_REASONS, 'not_active', 'failed']) {
      const key = `run.stop.remedy.reason.${reason}`;
      assert.notEqual(translate(locale, key), key, `${locale} ${key}`);
    }
  }
});

test('the stop card shows the Open in edit table button in en and ko', () => {
  const stop = { code: 'input_rejected', pointer: { kind: 'keyword', component: 'INTEGRATION', keyword: 'INTEGRATION', key: 'MAXDT' }, last_lines: [] };
  const en = r.renderFailedRun('en', stop, null, { onOpenEditRow: () => true });
  const ko = r.renderFailedRun('ko', stop, null, { onOpenEditRow: () => true });
  assert.match(en, />Open in edit table</);
  assert.match(ko, />편집 표에서 열기</);
  assert.doesNotMatch(r.renderFailedRun('en', stop), />Open in edit table</, 'no button without a way to open the table');
});

test('with no case open the click says so instead of doing nothing', async () => {
  const s = spy({ rel: 'case.genkey', row_id: 'integration.end_time_s', reason_key: 'row' });
  assert.deepEqual(await openStopRemedy('r', { ...s.deps, activeCase: null }), { reasonKey: 'run.stop.remedy.reason.not_active' });
  assert.deepEqual(s.opened, []);
});
