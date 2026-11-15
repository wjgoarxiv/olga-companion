import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('M0 step mapping: statuses derive from observable app state only', async () => {
  const { deriveStepStates } = await import('../src/shell/useStepState.ts');
  const base = {
    activeCaseName: null, tabCount: 0, hasRunOutputs: false,
    errorCount: 0, hasEvidence: false, preferredResultId: null,
  };
  // No case: only ① is current, the rest are upcoming.
  assert.deepEqual(deriveStepStates(base).map((s) => s.status),
    ['current', 'upcoming', 'upcoming', 'upcoming', 'upcoming']);
  // Case selected, no fluid table: ① done, ③ blocked. ② is not current and
  // ④ is not in progress — the blocked check is the only you-are-here.
  const cased = { ...base, activeCaseName: 'case-a.genkey' };
  assert.deepEqual(deriveStepStates(cased).map((s) => s.status),
    ['done', 'upcoming', 'blocked', 'upcoming', 'upcoming']);
  // Missing .tab blocks ③ with the noTab reason.
  const blocked = deriveStepStates(cased);
  assert.equal(blocked[2].status, 'blocked');
  assert.equal(blocked[2].reason, 'noTab');
  // Published errors block ③ with the errors reason (tab present).
  const errored = deriveStepStates({ ...cased, tabCount: 1, errorCount: 2 });
  assert.equal(errored[2].status, 'blocked');
  assert.equal(errored[2].reason, 'errors');
  // Evidence + tab + no errors completes ② and ③.
  const readyInput = { ...cased, tabCount: 1, hasEvidence: true };
  assert.deepEqual(deriveStepStates(readyInput).map((s) => s.status),
    ['done', 'done', 'done', 'current', 'upcoming']);
  // Run outputs complete ④ and make ⑤ current; opening one completes ⑤.
  const outputsInput = { ...readyInput, hasRunOutputs: true };
  assert.deepEqual(deriveStepStates(outputsInput).map((s) => s.status),
    ['done', 'done', 'done', 'done', 'current']);
  const opened = deriveStepStates({ ...outputsInput, preferredResultId: 'r1' });
  assert.ok(opened.every((s) => s.status === 'done'));
});

test('M0 step bar: one highlighted next action, allow-listed commands only', async () => {
  const bar = await read('../src/shell/StepBar.tsx');
  assert.match(bar, /data-stepbar/);
  assert.match(bar, /STEPBAR_DETAIL_ID/);
  assert.match(bar, /aria-current/);
  for (const call of ["onRunCommand('validate')", "onRunCommand('preview-run')", "onSelectView('results')", 'act: onNewCase']) {
    assert.ok(bar.includes(call), `next action routes through ${call}`);
  }
  assert.doesNotMatch(bar, /run_execute|executeApproval|onApprove|doRun|mintApproval|approval_token/);
  // The step bar never writes the composer itself: it only invokes the shell
  // draft callbacks. The interface may name setInput as a type, never a call.
  assert.doesNotMatch(bar, /setInput\(|queueInput|\.send\(/);
});

test('M0 ① detail: 만들기 entry is capability-gated, never a dead button', async () => {
  const bar = await read('../src/shell/StepBar.tsx');
  const guide = await read('../src/SimulationGuide.tsx');
  const hook = await read('../src/shell/useStepState.ts');
  assert.match(bar, /createFluidAction/);
  assert.match(bar, /CREATE_FLUID_TABLE_EVENT/);
  assert.match(bar, /SHELL_COMMANDS/);
  assert.match(hook, /olga:create-fluid-table/);
  assert.match(guide, /createFluidAction/);
  assert.match(guide, /stepbar\.next\.createFluid/);
});

test('M1 dock link: single one-line row to the step bar detail', async () => {
  const guide = await read('../src/SimulationGuide.tsx');
  const hook = await read('../src/shell/useStepState.ts');
  const css = await read('../src/styles/simulation-guide.css');
  assert.match(guide, /simulation-guide-link/);
  assert.match(guide, /href="#stepbar-detail"/);
  assert.match(guide, /STEPBAR_DETAIL_EVENT/);
  assert.match(hook, /olga:open-stepbar-detail/);
  assert.match(hook, /stepbar-detail['"]/);
  assert.match(guide, /olga:open-simulation-guide/);
  assert.match(css, /\.simulation-guide-link\s*\{[^}]*text-overflow:\s*ellipsis/s);
  assert.match(css, /\.simulation-guide-link\s*\{[^}]*white-space:\s*nowrap/s);
});

test('M0/M1 i18n: stepbar.* keys resolve in ko+en, en carries no Hangul', async () => {
  const keys = [
    'stepbar.guideLink',
    'stepbar.status.done', 'stepbar.status.current', 'stepbar.status.blocked', 'stepbar.status.upcoming',
    'stepbar.next.create', 'stepbar.next.edit', 'stepbar.next.validate', 'stepbar.next.run', 'stepbar.next.results',
    'stepbar.next.createFluid',
    'stepbar.blockedNoTab', 'stepbar.blockedErrors',
    'stepbar.detail', 'stepbar.nextLabel', 'stepbar.position',
    'stepbar.prevStep', 'stepbar.nextStep',
    'stepbar.short.create', 'stepbar.short.edit', 'stepbar.short.validate',
    'stepbar.short.run', 'stepbar.short.analyze',
  ];
  for (const key of keys) {
    // translate falls back to the key itself: inequality proves the entry exists.
    assert.notEqual(translate('ko', key), key, `${key} resolves in ko`);
    assert.ok(translate('ko', key)?.length > 0, `${key} resolves in ko`);
    const en = translate('en', key);
    assert.notEqual(en, key, `${key} resolves in en`);
    assert.ok(en?.length > 0, `${key} resolves in en`);
    assert.doesNotMatch(en, /[가-힣]/, `${key} en carries no Hangul`);
  }
  assert.match(translate('ko', 'stepbar.blockedErrors', { count: 2 }), /2/);
});
