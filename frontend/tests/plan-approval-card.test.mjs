import assert from 'node:assert/strict';
import test from 'node:test';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';
import { planOutcome, planStepRows } from '../src/planApproval.mjs';

const render = await approvalCardRenderer();

const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });

const display = {
  plan: {
    steps: [
      {
        index: 1,
        kind: 'fluids_draft_mfl',
        fields: [row('file', 'synthetic.mfl'), row('label', 'SYN1'), row('model', 'SRK')],
      },
      { index: 2, kind: 'case_publish', fields: [row('file', 'cases/new.genkey')] },
      {
        index: 3,
        kind: 'run_execute',
        fields: [row('timeout', '600', 's')],
        bound_to: 2,
        unknown: ['run_case'],
      },
    ],
  },
};

const request = {
  name: 'action_plan',
  call_id: 'call_plan',
  pending_id: 'pending_plan',
  args: { steps: [{ kind: 'fluids_draft_mfl', args: {} }] },
  display,
  expires_at: Math.floor(Date.now() / 1000) + 1500,
};

const result = (states) => ({
  ok: states.every((state) => state === 'done'),
  steps: states.map((state, index) => ({ index: index + 1, kind: display.plan.steps[index].kind, state })),
});

test('the plan card lists one row per step in English, with what is not known yet', () => {
  const html = render('en', request);
  assert.match(html, /Approval needed — Run these steps in order/);
  const items = html.match(/<li[ >]/g) ?? [];
  assert.equal(items.length, 3, 'one row per step');
  for (const text of [
    'Step 1', 'Step 2', 'Step 3', 'Write the Multiflash draft file', 'Save the reviewed case', 'Run the simulation',
    'synthetic.mfl', 'SYN1', 'SRK', 'cases/new.genkey', '600 s',
    'The case saved in step 2 (not known yet)',
  ]) {
    assert.ok(html.includes(text), `en card shows ${text}`);
  }
  assert.ok(html.indexOf('Step 1') < html.indexOf('Step 2') && html.indexOf('Step 2') < html.indexOf('Step 3'));
  assert.match(html, /Approve and run the steps/);
  assert.match(html, /each step is checked again/i);
});

test('the plan card reads in Korean through the dictionary', () => {
  const html = render('ko', request);
  assert.match(html, /승인 필요 — 다음 단계를 차례로 실행/);
  for (const text of ['1단계', '2단계', '3단계', '승인하고 단계 실행', '2단계에서 저장한 사례 (아직 알 수 없음)']) {
    assert.ok(html.includes(text), `ko card shows ${text}`);
  }
  assert.doesNotMatch(html, /action_plan|Step 1/);
});

test('the plan card is one alert dialog and carries no capability or hash', () => {
  const html = render('en', request);
  assert.equal((html.match(/role="alertdialog"/g) ?? []).length, 1);
  assert.doesNotMatch(html, /approval_token|idempotency|sha256|transaction/i);
});

test('every step shows its state once the result is known, and the stop point is named', () => {
  const stopped = { ...result(['done', 'failed', 'not_run']), stopped_at: 2 };
  const html = render('en', request, { result: stopped, lifecycle: 'finalizing' });
  assert.ok(html.includes('Done'));
  assert.ok(html.includes('Stopped here'));
  assert.ok(html.includes('Not run'));
});

test('a resolved plan keeps its steps and says what happened', () => {
  const stopped = { ...result(['done', 'failed', 'not_run']), stopped_at: 2 };
  const en = render('en', request, { resolved: true, lifecycle: 'completed', result: stopped });
  assert.match(en, /The sequence stopped/);
  assert.match(en, /Step 2/);
  assert.ok(en.includes('Not run'));
  const ko = render('ko', request, { resolved: true, lifecycle: 'completed', result: stopped });
  assert.match(ko, /순서가 중간에 멈췄습니다/);
  assert.ok(ko.includes('실행하지 않음'));
  const finished = render('en', request, { resolved: true, lifecycle: 'completed', result: result(['done', 'done', 'done']) });
  // The third step runs the simulation: done means started, so the card must not claim it finished.
  assert.match(finished, /the simulation has started/);
  assert.doesNotMatch(finished, /All steps are done/);
});

test('an uncertain step is shown as unknown, never as done', () => {
  const html = render('en', request, {
    resolved: false,
    lifecycle: 'uncertain',
    result: result(['done', 'uncertain', 'not_run']),
  });
  assert.ok(html.includes('Outcome unknown'));
  assert.match(html, /One step has an unknown outcome/);
});

test('the presenter pairs display rows with result states and survives junk', () => {
  const rows = planStepRows(display, result(['done', 'failed', 'not_run']));
  assert.deepEqual(rows.map((r) => [r.index, r.kind, r.state]), [
    [1, 'fluids_draft_mfl', 'done'], [2, 'case_publish', 'failed'], [3, 'run_execute', 'not_run'],
  ]);
  assert.equal(rows[2].boundTo, 2);
  assert.deepEqual(planStepRows(display, undefined).map((r) => r.state), ['waiting', 'waiting', 'waiting']);
  assert.deepEqual(planStepRows(undefined, undefined), []);
  assert.deepEqual(planStepRows({ plan: { steps: 'x' } }, { steps: 5 }), []);
  assert.equal(planOutcome(result(['done', 'done'])), 'completed');
  assert.equal(planOutcome({ ...result(['done', 'failed']) }), 'stopped');
  assert.equal(planOutcome(result(['done', 'uncertain'])), 'uncertain');
  assert.equal(planOutcome(undefined), null);
});

test('a reloaded plan approval keeps its per-step result for the card', async () => {
  const { rehydrateTimeline } = await import('../src/timeline.ts');
  const steps = [
    { index: 1, kind: 'fluids_draft_mfl', state: 'done' },
    { index: 2, kind: 'case_publish', state: 'failed' },
    { index: 3, kind: 'run_execute', state: 'not_run' },
  ];
  const items = rehydrateTimeline([
    {
      schema_version: 1,
      sequence: 3,
      record: 'approval',
      record_id: 'approval_plan_done',
      pending_id: 'pending_plan',
      call_id: 'call_plan',
      name: 'action_plan',
      args: { steps: [] },
      display,
      state: 'completed',
      result: { ok: false, steps },
    },
  ]);
  const card = items.find((item) => item.kind === 'approval');
  assert.deepEqual(card?.result?.steps, steps);
  assert.equal(card?.request.display, display);
});
