import assert from 'node:assert/strict';
import test from 'node:test';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';
import { approvalHookMounter } from './helpers/render-approval-hook.mjs';
import * as planApproval from '../src/planApproval.mjs';
import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

const { planOutcome, planSettledState, planStepRows } = planApproval;
const render = await approvalCardRenderer();
const mountApprovalHook = await approvalHookMounter();

const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });

const inputs = [
  { group: 'Boundary', name: 'SOURCE Pressure', value: '2000000', unit: 'Pa' },
  { group: 'Boundary', name: 'SINK Pressure', value: '1000000', unit: 'Pa' },
  { group: 'Simulation', name: 'End time', value: '7200', unit: 's' },
];

const display = {
  plan: {
    steps: [
      { index: 1, kind: 'case_publish', fields: [row('file', 'cases/new.genkey')], inputs },
      {
        index: 2,
        kind: 'run_execute',
        fields: [row('timeout', '600', 's')],
        bound_to: 1,
        unknown: ['run_case', 'runtime', 'executable', 'output'],
      },
    ],
  },
};

const request = {
  name: 'action_plan',
  call_id: 'call_plan',
  pending_id: 'pending_plan',
  args: { steps: [] },
  display,
  expires_at: Math.floor(Date.now() / 1000) + 1500,
};

const steps = (...states) => states.map((state, index) => ({
  index: index + 1,
  kind: display.plan.steps[index].kind,
  state,
}));

test('the publish row shows the reviewed inputs a single card shows, grouped', () => {
  const html = render('en', request);
  for (const text of ['Boundary', 'SOURCE Pressure', '2000000 Pa', 'SINK Pressure', 'Simulation', 'End time', '7200 s']) {
    assert.ok(html.includes(text), `the plan card shows ${text}`);
  }
  assert.equal((html.match(/Boundary/g) ?? []).length, 1, 'one heading per group');
  assert.doesNotMatch(html, /approval_token|idempotency|sha256|transaction/i);
});

test('a bound run row says plainly that the runtime is chosen and re-checked when the step starts', () => {
  const en = render('en', request);
  assert.match(en, /Runtime/);
  assert.match(en, /Executable/);
  assert.match(en, /Output location/);
  assert.equal((en.match(/Chosen and re-checked when this step starts/g) ?? []).length, 3);
  const ko = render('ko', request);
  assert.equal((ko.match(/이 단계가 시작될 때 선택하고 다시 확인합니다/g) ?? []).length, 3);
});

test('an exact run row shows the detected runtime, executable, output and case', () => {
  const exact = {
    ...request,
    display: {
      plan: {
        steps: [{
          index: 1,
          kind: 'run_execute',
          fields: [
            row('run_case', 'old.genkey'), row('runtime', 'olga-2025'), row('executable', 'OLGA-2025.exe'),
            row('output', 'managed-run-sandbox'), row('timeout', '60', 's'),
          ],
        }],
      },
    },
  };
  const html = render('en', exact);
  for (const text of ['old.genkey', 'olga-2025', 'OLGA-2025.exe', 'managed-run-sandbox', '60 s', 'Runtime', 'Executable']) {
    assert.ok(html.includes(text), `exact run row shows ${text}`);
  }
  assert.doesNotMatch(html, /Chosen and re-checked/);
});

test('a plan with no rows cannot be approved', () => {
  for (const empty of [{}, { plan: { steps: [] } }, undefined]) {
    const html = render('en', { ...request, display: empty });
    const approve = html.match(/<button[^>]*class="[^"]*\bapprove\b[^"]*"[^>]*>/)?.[0] ?? '';
    assert.ok(approve, 'the approve button is rendered');
    assert.match(approve, /disabled/, 'no reviewed rows, no approval');
    assert.ok(html.includes('no reviewed steps'), 'the card says why');
  }
  const ready = render('en', request).match(/<button[^>]*class="[^"]*\bapprove\b[^"]*"[^>]*>/)?.[0] ?? '';
  assert.doesNotMatch(ready, /disabled/);
});

test('a run step reads started, never done, and the sequence does not claim it finished', () => {
  const result = { ok: true, state: 'completed', steps: steps('done', 'done') };
  const html = render('en', request, { resolved: true, lifecycle: 'completed', result });
  assert.ok(html.includes('Started'));
  assert.doesNotMatch(html, /All steps are done/);
  assert.match(html, /the simulation has started/i);
  const ko = render('ko', request, { resolved: true, lifecycle: 'completed', result });
  assert.ok(ko.includes('실행 시작됨'));
  assert.doesNotMatch(ko, /모든 단계를 마쳤습니다/);
  assert.equal(planOutcome(result), 'started');
  assert.equal(planStepRows(display, result)[1].state, 'done', 'the data state stays done');
});

test('a sequence without a run step still reads as all done', () => {
  const result = { ok: true, state: 'completed', steps: steps('done').concat([]) };
  const onlyPublish = { ...request, display: { plan: { steps: [display.plan.steps[0]] } } };
  const html = render('en', onlyPublish, { resolved: true, lifecycle: 'completed', result });
  assert.match(html, /All steps are done/);
  assert.equal(planOutcome(result), 'completed');
});

test('the stopped row carries the reason from the step error', () => {
  const result = {
    ok: false,
    state: 'stopped',
    stopped_at: 2,
    steps: [
      { index: 1, kind: 'case_publish', state: 'done' },
      { index: 2, kind: 'run_execute', state: 'failed', error: 'The saved case did not validate cleanly, so the run was not started.' },
    ],
  };
  const rows = planStepRows(display, result);
  assert.equal(rows[1].error, 'The saved case did not validate cleanly, so the run was not started.');
  assert.equal(rows[0].error, '');
  const html = render('en', request, { resolved: true, lifecycle: 'completed', result });
  assert.ok(html.includes('Stopped here'));
  assert.ok(html.includes('did not validate cleanly'));
});

test('a plan that was closed before any step ran still reads as a failure', () => {
  const closed = { ok: false, state: 'stopped', error: 'The approved plan changed after it was approved; nothing was run.', steps: [] };
  assert.equal(planOutcome(closed), 'stopped');
  const html = render('en', request, { resolved: true, lifecycle: 'completed', result: closed });
  assert.match(html, /The sequence stopped/);
  assert.ok(html.includes('changed after it was approved'));
  assert.doesNotMatch(html, /All steps are done|Review closed/i);
  assert.ok(html.includes('Not run'), 'nothing in a closed plan is left waiting');
  assert.equal(planOutcome({ ok: true, steps: [] }), null, 'an empty successful result stays neutral');
});

test('the reserved table step has a label in both languages, so the card never shows a raw kind', () => {
  assert.ok(en['approval.plan.kind.fluids_generate_tab']);
  assert.ok(ko['approval.plan.kind.fluids_generate_tab']);
  const reserved = {
    ...request,
    display: { plan: { steps: [{ index: 1, kind: 'fluids_generate_tab', fields: [row('file', 'fluid.tab')] }] } },
  };
  for (const locale of ['en', 'ko']) {
    assert.doesNotMatch(render(locale, reserved), /fluids_generate_tab|approval\.plan\.kind/);
  }
});

// -------------------------------------------------------------- the real hook

function mount(execution) {
  const tools = [];
  const approvals = [];
  const api = mountApprovalHook({
    approvalCallIds: { current: new Set() },
    executeApproval: async () => execution,
    handleEvent: () => undefined,
    rejectApproval: async () => ({ state: 'rejected' }),
    refreshWorkspace: () => undefined,
    reportError: () => undefined,
    sessionId: 's1',
    setBusy: () => undefined,
    updateApproval: (callId, patch) => approvals.push({ callId, ...patch }),
    updateTool: (callId, patch) => tools.push({ callId, ...patch }),
    workspaceGeneration: { current: 0 },
    resumeApproval: async () => undefined,
  });
  return { api, tools, approvals };
}

test('a stopped plan never leaves its tool row completed after the model continues', async () => {
  const stopped = { ok: false, state: 'stopped', steps: steps('done', 'failed') };
  const { api, tools, approvals } = mount({ state: 'resume_pending', resume_allowed: true, result: stopped });
  await api.approve(request);
  assert.equal(tools.at(-1).status, 'failed');
  assert.equal(approvals.at(-1).lifecycle, 'failed');
  assert.equal(approvals.at(-1).resolved, true);
  assert.deepEqual(approvals.find((patch) => patch.result)?.result.steps, stopped.steps, 'the card keeps the step states');
  assert.ok(tools.every((patch) => patch.status !== 'completed'));
});

test('a plan that ran every step still settles as completed', async () => {
  const finished = { ok: true, state: 'completed', steps: steps('done', 'done') };
  const { api, tools, approvals } = mount({ state: 'resume_pending', resume_allowed: true, result: finished });
  await api.approve(request);
  assert.equal(tools.at(-1).status, 'completed');
  assert.equal(approvals.at(-1).lifecycle, 'completed');
  assert.equal(planSettledState(finished), 'completed');
  assert.equal(planSettledState({ ok: false, steps: [] , state: 'stopped' }), 'failed');
});
