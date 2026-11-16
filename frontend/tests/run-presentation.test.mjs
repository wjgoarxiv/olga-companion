import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { approveBlockedReason, liveRunStatus, runNextAction, runStopNotice, solverLogHighlights } from '../src/runPresentation.mjs';
import { readRunSource } from './run-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const LOG = [
  'READING FLUID PROP. FILE : fluid.tab',
  'WARNING 887 table value exceptions have been reg. for fluid',
  'ERROR: Pressure out of range in SECTION 3',
  'Elapsed simulation-time is now: 0.00 S',
].join('\n');

test('log highlights keep the fault lines and drop routine ones', () => {
  const result = solverLogHighlights(LOG);

  assert.equal(result.kind, 'fault');
  assert.deepEqual(result.lines, [
    'WARNING 887 table value exceptions have been reg. for fluid',
    'ERROR: Pressure out of range in SECTION 3',
  ]);
});

test('a log without a fault sentence says so and shows only its last lines', () => {
  const result = solverLogHighlights('a\nb\nc\nd\ne');

  assert.equal(result.kind, 'last-lines');
  assert.deepEqual(result.lines, ['c', 'd', 'e']);
  assert.deepEqual(solverLogHighlights(''), { kind: 'last-lines', lines: [] });
  assert.equal(solverLogHighlights('x'.repeat(500) + ' error').lines[0].length, 201);
});

test('next action never offers an automatic retry of an uncertain or failed run', () => {
  for (const state of ['failed', 'timed_out', 'recovery_unknown', 'supervision_unknown', 'cancelled']) {
    const text = runNextAction({ state, outputs: [] });
    assert.ok(text, state);
    assert.doesNotMatch(text, /자동으로 다시 시작합니다|재시도합니다/u, state);
  }
  assert.match(runNextAction({ state: 'failed' }), /자동으로 다시 시작되지 않습니다/u);
  assert.match(runNextAction({ state: 'running' }, true), /Retry run context/u);
  assert.equal(runNextAction({ state: 'running' }), null);
  assert.match(runNextAction({ state: 'completed', outputs: [{ suffix: '.TPL' }] }), /Results/u);
  assert.match(runNextAction({ state: 'completed', outputs: [{ suffix: '.out' }] }), /TPL 결과가 없어/u);
  assert.match(runNextAction({ state: 'completed', outputs: [] }), /기록된 결과 파일이 없습니다/u);
});

test('the approve button always states the first thing blocking it', () => {
  const valid = { selection_id: 's', validation: { valid: true } };

  assert.match(approveBlockedReason({ operationActive: true, runReady: true, preview: valid }), /진행 중/u);
  assert.match(approveBlockedReason({ operationActive: false, runReady: false, preview: valid }), /실행 환경/u);
  assert.match(approveBlockedReason({ operationActive: false, runReady: true, preview: null }), /Preview command/u);
  assert.match(approveBlockedReason({ operationActive: false, runReady: true, preview: { selection_id: 's', validation: { valid: false } } }), /검증이 실패/u);
  assert.equal(approveBlockedReason({ operationActive: false, runReady: true, preview: valid }), '');
  // A preview already used for a started run (finished, failed or uncertain) cannot launch again.
  assert.match(approveBlockedReason({ operationActive: false, runReady: true, preview: valid, usedSelectionId: valid.selection_id }), /이미 실행을 시작/u);
  assert.equal(approveBlockedReason({ operationActive: false, runReady: true, preview: valid, usedSelectionId: 'other' }), '');
});

test('only a live run drives live state; a restored receipt never does', () => {
  const receipt = { run_id: 'old', state: 'failed' };

  assert.equal(liveRunStatus(receipt, 'history'), null);
  assert.equal(liveRunStatus(receipt, 'live'), receipt);
  assert.equal(liveRunStatus(null, 'live'), null);
});

test('a restored receipt is history: it never shows as live state or progress', async () => {
  const run = await readRunSource();
  const lifecycle = await read('../src/useRunLifecycle.ts');
  const panel = await read('../src/RunFailurePanel.tsx');

  assert.match(lifecycle, /setStatusSource\(restored && !runStatusIsPollable\(restored\) \? 'history' : 'live'\)/);
  assert.match(run, /setStatusSource\('live'\)/, 'starting a run makes its status live');
  assert.match(run, /const liveStatus = liveRunStatus\(status, statusSource\)/, 'the panel derives live state only through the tested helper');
  assert.match(run, /liveStatus\?\.state \|\| 'ready'/, 'the panel header ignores a historical receipt');
  assert.match(run, /liveStatus && \(\s*<div ref=\{progressRef\}/, 'terminal progress is shown only for the live run');
  assert.match(panel, /t\('run\.historyNote'\)/);
  assert.match(panel, /aria-label=\{t\('run\.solverLogAria'\)\}>/);
  assert.match(run, /aria-describedby=\{blockedReason && !starting \? 'run-approve-hint' : undefined\}/);
});

test('the next step it names is always on screen, and a finished run needs a fresh preview', async () => {
  const [view, panel, actions] = await Promise.all([
    readFile(new URL('../src/RunView.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/RunFailurePanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/useRunActions.ts', import.meta.url), 'utf8'),
  ]);

  // supervision_unknown reported by the backend (no request error) still gets the Retry run context button.
  assert.match(panel, /t\('run\.errSupervision'\)[^]*?action=\{onRetryContext \?/);
  assert.match(view, /onRetryContext=\{retryContext\}/);
  assert.match(view, /error && errorRetriesContext \? undefined : lifecycle\.retryRunContext/);
  // A preview is consumed before the run call and only a new preview releases it.
  assert.match(actions, /setUsedSelectionId\(preview\.selection_id\);\s*const started/);
  assert.match(actions, /setPreview\(next\);\s*setUsedSelectionId\(''\)/);
});

test('a cancelled or timed-out run is presented as a stop, not as a case failure', async () => {
  const { ko } = await import('../src/i18n/ko.ts');
  const { en } = await import('../src/i18n/en.ts');
  const staleFailure = {
    code: 'native_process_failed',
    title: 'OLGA process failed',
    detail: 'The native process returned exit 1223; inspect the captured solver log for the case-specific cause.',
    action: 'Review the log and correct the reported condition before starting another run.',
    auto_retry_safe: false,
  };
  for (const [name, dict] of [['ko', ko], ['en', en]]) {
    const t = (key) => dict[key];
    const cancelled = runStopNotice({ state: 'cancelled', exit_code: 1223, failure: staleFailure }, t);
    const timedOut = runStopNotice({ state: 'timed_out', exit_code: 1460, failure: staleFailure }, t);
    for (const notice of [cancelled, timedOut]) {
      assert.ok(notice?.title && notice.detail, name);
      assert.doesNotMatch(`${notice.title}${notice.detail}${notice.action ?? ''}`, /1223|1460|process failed|실패|inspect|correct the reported|오류를 해결/iu, name);
    }
    assert.equal(cancelled.detail, name === 'ko' ? '사용자가 실행을 취소했습니다.' : 'You cancelled this run.');
    assert.equal(cancelled.action, null, name);
    assert.match(timedOut.detail, name === 'ko' ? /제한 시간/u : /time limit/u);
    assert.match(timedOut.action, name === 'ko' ? /제한 시간을 늘려/u : /Raise the run time limit/u);
  }
  assert.equal(runStopNotice({ state: 'failed', exit_code: 1, failure: staleFailure }, (key) => key), null);
  assert.equal(runStopNotice({ state: 'completed' }, (key) => key), null);
});

test('a timed-out run does not get the fix-the-case next step', () => {
  assert.doesNotMatch(runNextAction({ state: 'timed_out' }), /오류 줄/u);
  assert.match(runNextAction({ state: 'timed_out' }), /제한 시간/u);
  assert.match(runNextAction({ state: 'failed' }), /오류 줄/u);
});
