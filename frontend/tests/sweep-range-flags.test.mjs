// 0.1.20 row 9: the sweep preview warns about points outside the fluid table; it never blocks.
import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const progress = { kind: 'indeterminate', percent: null, simulated_s: null, end_s: null, source: 'none', observed_at: null };
const kase = (index, flags) => ({
  index, path: `c${index}.genkey`, valid: true, validation_errors: [], params: [], run_id: null, state: 'planned', ok: false,
  pvt_files: [], cancel_requested: false, solver_progress: progress, range_flags: flags,
});
const preview = {
  sweep_id: 's1', plan_id: 'p1', state: 'planned', ok: true, dry_run: true, base: 'base.genkey', case_count: 2,
  cases: [
    kase(0, []),
    kase(1, [
      { origin: 'INLET', kind: 'node', quantity: 'pressure', value: '80 bara', status: 'outside', relation: 'above' },
      { origin: 'SRC', kind: 'source', quantity: 'temperature', value: '29 C', status: 'near', relation: 'above' },
    ]),
  ],
};

test('a flagged case names the point, the value and the side of the table in en and ko', () => {
  const en = r.renderSweepPreview('en', preview);
  assert.match(en, /INLET pressure 80 bara is above the fluid table range/);
  assert.match(en, /SRC temperature 29 C is near the top of the fluid table range/);
  const ko = r.renderSweepPreview('ko', preview);
  assert.match(ko, /INLET 압력 80 bara: 유체 표 범위보다 높아요/);
  assert.match(ko, /SRC 온도 29 C: 유체 표 범위 위쪽 끝에 가까워요/);
});

test('an unflagged case shows no warning', () => {
  const en = r.renderSweepPreview('en', { ...preview, cases: [kase(0, [])] });
  assert.doesNotMatch(en, /fluid table range/);
});

test('every case state the sidecar sends is shown in words, never as its raw name (0.1.20 PVT)', () => {
  for (const state of ['planned', 'running', 'finalizing', 'supervision_unknown', 'completed', 'failed', 'cancelled', 'timed_out']) {
    const one = { ...preview, cases: [{ ...kase(0, []), state }] };
    for (const locale of ['en', 'ko']) {
      const html = r.renderSweepPreview(locale, one);
      const shown = /<strong>([^<]*)<\/strong>/.exec(html.slice(html.indexOf('sweep-case-copy')))?.[1];
      assert.ok(shown, `${locale} ${state}: no state text`);
      assert.doesNotMatch(shown, /_/, `${locale} shows the raw state ${state}`);
      if (locale === 'ko') assert.match(shown, /[가-힣]/, `ko ${state}: ${shown}`);
    }
  }
});

test('a case the sweep could not build says so with the reason, not "waiting" (0.1.20 PVT)', () => {
  const bad = { ...kase(0, []), valid: false, validation_errors: ['genkey_writer failed for WALL.THICKNESS: boom\nmore'] };
  const ko = r.renderSweepPreview('ko', { ...preview, cases: [bad] });
  assert.match(ko, /이 사례를 만들지 못했어요/);
  assert.match(ko, /genkey_writer failed for WALL\.THICKNESS: boom/);
  assert.doesNotMatch(ko, /스윕 대기 중/);
  const en = r.renderSweepPreview('en', { ...preview, cases: [bad] });
  assert.match(en, /This case could not be built/);
});

test('Run sweep is offered only when every previewed case was built', () => {
  assert.equal(r.sweepPreviewRunnable(preview), true);
  assert.equal(r.sweepPreviewRunnable({ ...preview, cases: [kase(0, []), { ...kase(1, []), valid: false }] }), false);
  assert.equal(r.sweepPreviewRunnable(null), false);
});

test('the sweep summary names the changed value and the run state in words, not raw data (0.1.20 PVT)', () => {
  const rows = [0, 1].map((index) => ({
    index, params: [{ keyword: 'WALL', key: 'THICKNESS', value: index ? 0.03 : 0.005, label: null }],
    run_id: `r${index}`, state: 'completed', ok: true, tpl: 'case.tpl',
    outputs: { PT: { value: 1042009, unit: 'PA' }, LIQC: { value: null, reason: "Could not read a series for 'LIQC' from case.tpl." } },
  }));
  const ko = r.renderSweepSummary('ko', rows);
  assert.match(ko, /WALL\.THICKNESS = 0\.005/);
  assert.doesNotMatch(ko, /"keyword"/);
  assert.doesNotMatch(ko, />completed</);
  assert.match(ko, /완료/);
  assert.match(ko, /값 없음: Could not read a series/);
  const labelled = r.renderSweepSummary('en', [{ ...rows[0], params: [{ keyword: 'SOURCE', key: 'MASSFLOW', value: 2, label: 'FEED' }] }]);
  assert.match(labelled, /SOURCE\.MASSFLOW \(FEED\) = 2/);
});
