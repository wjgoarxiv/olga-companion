import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function patrolItem(id, result) {
  return { kind: 'tool', id, name: 'run_patrol', callId: `call-${id}`, status: 'completed', result };
}

function resultFile(overrides) {
  return {
    id: 'run:case-a/out.tpl',
    name: 'out.tpl',
    rel: 'case-a/out.tpl',
    origin: 'run',
    size: 10,
    suffix: '.tpl',
    modified_ns: 1,
    run_id: 'run-1',
    source_name: 'case-a.genkey',
    ...overrides,
  };
}

test('task16: newest unhandled completed patrol completion is found', async () => {
  const { findRunCompletion } = await import('../src/runCompletion.ts');
  const timeline = [
    patrolItem('i1', { run_id: 'run-1', terminal: true, state: 'completed' }),
    patrolItem('i2', { run_id: 'run-2', terminal: true, state: 'completed' }),
  ];
  assert.deepEqual(findRunCompletion(timeline, new Set()), { runId: 'run-2' });
  assert.deepEqual(findRunCompletion(timeline, new Set(['run-2'])), { runId: 'run-1' });
  assert.equal(findRunCompletion(timeline, new Set(['run-1', 'run-2'])), null);
});

test('task16: patrol observations and failed terminals never complete', async () => {
  const { findRunCompletion } = await import('../src/runCompletion.ts');
  const bounded = [patrolItem('i1', { run_id: 'run-1', terminal: false, state: 'running' })];
  assert.equal(findRunCompletion(bounded, new Set()), null);
  const failed = [patrolItem('i1', { run_id: 'run-9', terminal: true, state: 'failed' })];
  assert.equal(findRunCompletion(failed, new Set()), null);
  const otherTool = [{ kind: 'tool', id: 'i1', name: 'case_publish', callId: 'c1', status: 'completed', result: { run_id: 'run-9', terminal: true, state: 'completed' } }];
  assert.equal(findRunCompletion(otherTool, new Set()), null);
  const noRunId = [patrolItem('i1', { terminal: true, state: 'completed' })];
  assert.equal(findRunCompletion(noRunId, new Set()), null);
  assert.equal(findRunCompletion([], new Set()), null);
});

test('task16: completed run resolves to its own output, else the active case newest', async () => {
  const { pickRunResult } = await import('../src/runCompletion.ts');
  const old = resultFile({ id: 'run:case-a/old.tpl', modified_ns: 1, run_id: 'run-1' });
  const fresh = resultFile({ id: 'run:case-a/new.tpl', modified_ns: 9, run_id: 'run-2' });
  const other = resultFile({ id: 'run:case-b/out.tpl', modified_ns: 50, run_id: 'run-3', source_name: 'case-b.genkey' });
  assert.equal(pickRunResult([old, fresh, other], { runId: 'run-2', activeCaseName: 'case-a.genkey' })?.id, 'run:case-a/new.tpl');
  assert.equal(pickRunResult([old, other], { runId: 'run-missing', activeCaseName: 'case-a.genkey' })?.id, 'run:case-a/old.tpl');
  assert.equal(pickRunResult([other], { runId: 'run-missing', activeCaseName: 'case-a.genkey' }), null);
  assert.equal(pickRunResult([], { runId: 'run-1', activeCaseName: 'case-a.genkey' }), null);
});

test('task16: Run view announces only the pollable-to-completed transition', async () => {
  const { shouldAnnounceRunCompletion } = await import('../src/runCompletion.ts');
  const running = { run_id: 'run-1', state: 'running' };
  const completed = { run_id: 'run-1', state: 'completed' };
  assert.equal(shouldAnnounceRunCompletion(running, completed), 'run-1');
  assert.equal(shouldAnnounceRunCompletion(null, completed), null);
  assert.equal(shouldAnnounceRunCompletion(running, { run_id: 'run-1', state: 'failed' }), null);
  assert.equal(shouldAnnounceRunCompletion(completed, completed), null);
  assert.equal(shouldAnnounceRunCompletion(running, { run_id: 'run-2', state: 'completed' }), null);
});

test('task16: step bar reaches Results once the completed output is preferred', async () => {
  const { deriveStepStates } = await import('../src/shell/useStepState.ts');
  const states = deriveStepStates({
    activeCaseName: 'case-a.genkey', tabCount: 1, hasRunOutputs: false,
    errorCount: 0, hasEvidence: true, preferredResultId: 'run:case-a/new.tpl',
  });
  const byId = Object.fromEntries(states.map((s) => [s.id, s.status]));
  assert.equal(byId.run, 'done');
  assert.equal(byId.analyze, 'done');
});

test('task16: App opens Results on completion but keeps the view while typing', async () => {
  const [app, opener] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/useRunCompletionOpener.ts'),
  ]);
  assert.match(app, /useRunCompletionOpener/);
  assert.match(app, /onRunCompleted/);
  assert.match(app, /selectView\('results'\)/);
  assert.match(opener, /findRunCompletion/);
  assert.match(opener, /pickRunResult/);
  assert.match(opener, /rescanResultInventory/);
  assert.match(opener, /composerText\.trim\(\)/);
  assert.match(opener, /preferResult\(picked\.id\)/);
});

test('task16: Run view reports terminal completion without switching itself', async () => {
  const run = await read('../src/RunView.tsx');
  assert.match(run, /onRunCompleted/);
  assert.match(run, /shouldAnnounceRunCompletion/);
  assert.doesNotMatch(run, /selectView\('results'\)/);
});

test('task16: patrol metric labels and values resolve in ko+en', async () => {
  const keys = [
    'lifecycle.patrolMetric.simulationTime',
    'lifecycle.patrolMetric.step',
    'lifecycle.patrolMetric.adaptiveTotalSteps',
    'lifecycle.patrolMetric.phase',
    'lifecycle.patrolMetric.liveness',
    'lifecycle.phase.running',
    'lifecycle.phase.finalizing',
    'lifecycle.phase.terminal',
    'lifecycle.phase.supervisionUnknown',
    'lifecycle.phase.indeterminate',
    'lifecycle.liveness.supervised',
    'lifecycle.liveness.terminal',
    'lifecycle.liveness.supervisionUnknown',
    'lifecycle.liveness.indeterminate',
    'casespec.pipesSectionsUnavailable',
    'casespec.valueUnavailable',
  ];
  for (const key of keys) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.notEqual(ko, key, `${key} resolves in ko`);
    assert.notEqual(en, key, `${key} resolves in en`);
    assert.notEqual(ko, en, `${key} is translated, not copied`);
    assert.doesNotMatch(en, /[가-힣]/, `${key} en carries no Hangul`);
  }
  assert.match(translate('en', 'casespec.pipesSectionsUnavailable', { pipes: 0 }), /0/);
  assert.match(translate('ko', 'casespec.pipesSectionsUnavailable', { pipes: 0 }), /0/);
});

test('task16: patrol card renders dictionary labels, validate card the dictionary count', async () => {
  const [lifecycle, casespec] = await Promise.all([
    read('../src/LifecycleEvidence.tsx'),
    read('../src/CaseSpecEvidence.tsx'),
  ]);
  assert.match(lifecycle, /lifecycle\.patrolMetric\./);
  assert.match(lifecycle, /lifecycle\.phase\./);
  assert.match(lifecycle, /lifecycle\.liveness\./);
  assert.doesNotMatch(casespec, /return 'unavailable'/);
  assert.match(casespec, /casespec\.pipesSectionsUnavailable/);
  assert.match(casespec, /casespec\.valueUnavailable/);
});

test('task16: sweep flags raw wire-key labels and raw unavailable fallbacks', async () => {
  const { scanRawKeyFallbacks } = await import('../../scripts/find_untranslated_ui.mjs');
  const [lifecycle, casespec] = await Promise.all([
    read('../src/LifecycleEvidence.tsx'),
    read('../src/CaseSpecEvidence.tsx'),
  ]);
  const auditOnly = 'export function Audit() {\n return <dl>{rows.map(([key]) => <div key={key}><dt>{key.replaceAll(\'_\', \' \')}</dt></div>)}</dl>;\n}';
  assert.ok(scanRawKeyFallbacks(auditOnly).length > 0, 'raw key prettification is flagged');
  assert.ok(scanRawKeyFallbacks("function value(v) {\n return 'unavailable';\n}").length > 0, 'raw unavailable fallback is flagged');
  assert.deepEqual(scanRawKeyFallbacks('const ok = t(\'lifecycle.audit\') ?? \'Audit receipt\';'), []);
  assert.ok(scanRawKeyFallbacks(lifecycle).every((f) => f.text.includes('reason.replaceAll') || f.text.includes('key.replaceAll')),
    'no unkeyed raw labels remain in the patrol card');
  assert.deepEqual(scanRawKeyFallbacks(casespec).filter((f) => f.text.includes('unavailable')), []);
});

test('task16: a failed live tool result keeps its short reason for the card', async () => {
  const controller = await read('../src/useChatController.ts');
  assert.doesNotMatch(controller, /!failed \? \{ result \} : \{\}/, 'a failed result is no longer dropped');
  assert.match(controller, /failed && approvalCallIds\.current\.has\(callId\) \? \{\} : \{ result \}/);
});

test('task16: completions already in a restored or reopened chat never open Results', async () => {
  const { collectCompletedRunIds } = await import('../src/runCompletion.ts');
  const timeline = [
    patrolItem('a', { run_id: 'old-ok', terminal: true, state: 'completed' }),
    patrolItem('b', { run_id: 'old-bad', terminal: true, state: 'failed' }),
  ];
  assert.deepEqual([...collectCompletedRunIds(timeline)], ['old-ok']);
  const opener = await read('../src/useRunCompletionOpener.ts');
  assert.match(opener, /sessionId/, 'the opener re-seeds when the chat session changes');
  assert.match(opener, /collectCompletedRunIds\(timeline\)/);
});

test('task16: the step bar keeps Results done after the Results view consumes the preferred output', async () => {
  const app = await read('../src/App.tsx');
  assert.match(app, /<StepBarSlot[^>]*preferredResultId=\{shownResultId\}/, 'the step bar reads the shown result, not the one-shot preference');
  assert.match(app, /onPreferredResultConsumed=\{\(\) => setPreferredResultId\(null\)\}/, 'consuming the preference leaves the shown result alone');
  assert.match(app, /preferResult: showResult/);
});

test('task16: runs the chat launched are found even when the model never patrols them', async () => {
  const { collectLaunchedRunIds } = await import('../src/runCompletion.ts');
  const timeline = [
    { kind: 'tool', id: 'p', name: 'action_plan', callId: 'c1', status: 'completed', result: { state: 'completed', steps: [
      { index: 1, kind: 'case_publish', state: 'done', result: { destination_rel: 'x.genkey' } },
      { index: 2, kind: 'run_execute', state: 'done', result: { run_id: 'plan-run', state: 'running' } },
    ] } },
    { kind: 'tool', id: 'r', name: 'run_execute', callId: 'c2', status: 'completed', result: { run_id: 'direct-run', state: 'running' } },
    { kind: 'tool', id: 'f', name: 'run_execute', callId: 'c3', status: 'failed', result: { error: 'refused' } },
  ];
  assert.deepEqual([...collectLaunchedRunIds(timeline)], ['plan-run', 'direct-run']);
  const opener = await read('../src/useRunCompletionOpener.ts');
  assert.match(opener, /collectLaunchedRunIds/, 'launched runs are watched');
  assert.match(opener, /runStatus\(/, 'the opener asks the runner for the terminal state');
  assert.match(opener, /runStatusIsPollable/, 'polling stops at a terminal state');
});

test('task16: an open Results view reloads its list when a finished run hands it an output', async () => {
  // The view loaded its list only when it mounted, so a run that finished while Results was
  // open left the new output out until "Refresh results" was pressed.
  const view = await read('../src/ResultsView.tsx');
  assert.match(view, /useEffect\(\(\) => \{\s*if \(preferredResultId\) void refreshResults\(true\);\s*\}, \[preferredResultId\]\);/);
});

test('task16: a chat that stops watching a run says the run goes on and where to follow it', async () => {
  // The bounded patrol card read "observation limit ... no terminal state is being inferred"
  // over a 0 % meter, which looked like a stalled run.
  const { en } = await import('../src/i18n/en.ts');
  const { ko } = await import('../src/i18n/ko.ts');
  for (const strings of [en, ko]) {
    assert.doesNotMatch(strings['lifecycle.patrolObserved'], /[Pp]atrol|패트롤/);
    assert.doesNotMatch(strings['lifecycle.patrolBoundedDetail'], /[Pp]atrol|패트롤|bounded|infer/);
  }
  assert.match(en['lifecycle.patrolBoundedDetail'], /Run view/);
  assert.match(ko['lifecycle.patrolBoundedDetail'], /실행 화면/);
});
