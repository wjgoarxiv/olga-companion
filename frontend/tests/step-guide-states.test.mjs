import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const base = {
  activeCaseName: null,
  tabCount: 0,
  hasRunOutputs: false,
  errorCount: 0,
  hasEvidence: false,
  preferredResultId: null,
  hasWorkspace: true,
  runInFlight: false,
};

function statuses(states) {
  return states.map((step) => step.status);
}

function oneHere(states) {
  const attention = states.filter((step) => step.status === 'current' || step.status === 'blocked');
  assert.equal(attention.length, 1, `exactly one you-are-here, got ${statuses(states).join(',')}`);
  assert.equal(states.filter((step) => step.status === 'current').length <= 1, true);
}

test('deriveStepStates: no workspace, no case, case without a table', async () => {
  const { deriveStepStates } = await import('../src/shell/useStepState.ts');
  const noWorkspace = deriveStepStates({ ...base, hasWorkspace: false });
  assert.deepEqual(statuses(noWorkspace), ['blocked', 'upcoming', 'upcoming', 'upcoming', 'upcoming']);
  assert.equal(noWorkspace[0].reason, 'noWorkspace');
  oneHere(noWorkspace);

  const noCase = deriveStepStates(base);
  assert.deepEqual(statuses(noCase), ['current', 'upcoming', 'upcoming', 'upcoming', 'upcoming']);
  oneHere(noCase);

  const noTab = deriveStepStates({ ...base, activeCaseName: 'case-a.genkey', tabCount: 0 });
  assert.deepEqual(statuses(noTab), ['done', 'upcoming', 'blocked', 'upcoming', 'upcoming']);
  assert.equal(noTab[2].reason, 'noTab');
  assert.equal(noTab.filter((step) => step.status === 'current').length, 0);
  oneHere(noTab);
});

test('deriveStepStates: validation errors, validated, run in flight, outputs, result open', async () => {
  const { deriveStepStates } = await import('../src/shell/useStepState.ts');
  const cased = { ...base, activeCaseName: 'case-a.genkey', tabCount: 1 };

  const errors = deriveStepStates({ ...cased, errorCount: 2 });
  assert.equal(errors[2].status, 'blocked');
  assert.equal(errors[2].reason, 'errors');
  assert.equal(errors[2].errorCount, 2);
  assert.notEqual(errors[3].status, 'current');
  oneHere(errors);

  const validated = deriveStepStates({ ...cased, hasEvidence: true });
  assert.deepEqual(statuses(validated), ['done', 'done', 'done', 'current', 'upcoming']);
  assert.equal(validated[3].reason, null);
  oneHere(validated);

  const flying = deriveStepStates({ ...cased, hasEvidence: true, runInFlight: true });
  assert.equal(flying[3].status, 'current');
  assert.equal(flying[3].reason, 'running');
  assert.equal(flying[4].status, 'upcoming');
  oneHere(flying);

  const outputs = deriveStepStates({ ...cased, hasEvidence: true, hasRunOutputs: true });
  assert.deepEqual(statuses(outputs), ['done', 'done', 'done', 'done', 'current']);
  oneHere(outputs);

  const opened = deriveStepStates({ ...cased, hasEvidence: true, hasRunOutputs: true, preferredResultId: 'r1' });
  assert.ok(opened.every((step) => step.status === 'done'));
  assert.equal(opened.filter((step) => step.status === 'current' || step.status === 'blocked').length, 0);
});

test('deriveNextAction names the concrete action and stays quiet when none exists', async () => {
  const { deriveStepStates, deriveNextAction } = await import('../src/shell/useStepState.ts');
  const next = (inputs, extra = {}) => deriveNextAction({
    states: deriveStepStates(inputs),
    canCreateFluid: true,
    activeView: null,
    ...extra,
  });

  assert.equal(next({ ...base, hasWorkspace: false }).labelKey, 'stepbar.next.openWorkspace');
  assert.equal(next(base).labelKey, 'stepbar.next.create');
  assert.equal(next({ ...base, activeCaseName: 'case-a.genkey' }).labelKey, 'stepbar.next.createFluid');
  assert.equal(next({ ...base, activeCaseName: 'case-a.genkey' }, { canCreateFluid: false }).kind, 'none');

  const cased = { ...base, activeCaseName: 'case-a.genkey', tabCount: 1 };
  assert.equal(next(cased).labelKey, 'stepbar.next.validate');
  assert.equal(next({ ...cased, errorCount: 3 }).labelKey, 'stepbar.next.validate');
  assert.equal(next({ ...cased, hasEvidence: true }).labelKey, 'stepbar.next.run');
  assert.equal(next({ ...cased, hasEvidence: true, runInFlight: true }).labelKey, 'stepbar.next.openRun');
  assert.equal(next({ ...cased, hasEvidence: true, hasRunOutputs: true }).labelKey, 'stepbar.next.results');
  assert.equal(
    next({ ...cased, hasEvidence: true, hasRunOutputs: true, preferredResultId: 'r1' }, { activeView: 'results' }).labelKey,
    'stepbar.next.edit',
  );
  assert.equal(
    next({ ...cased, hasEvidence: true, hasRunOutputs: true, preferredResultId: 'r1' }, { activeView: 'workspace' }).labelKey,
    'stepbar.next.results',
  );
});

test('a live patrol marks the run in flight; a terminal patrol clears it', async () => {
  const { timelineRunInFlight } = await import('../src/shell/useStepState.ts');
  const patrol = (state, terminal) => ({
    kind: 'tool', id: 'p', name: 'run_patrol', callId: 'c', status: 'completed',
    result: { state, terminal, run_id: 'run-1' },
  });
  assert.equal(timelineRunInFlight([]), false);
  assert.equal(timelineRunInFlight([patrol('running', false)]), true);
  assert.equal(timelineRunInFlight([patrol('running', false), patrol('completed', true)]), false);
  assert.equal(timelineRunInFlight([{
    kind: 'tool', id: 'e', name: 'run_execute', callId: 'c', status: 'running', result: { run_id: 'run-1' },
  }]), true);
});

test('step bar shows one here-marker and the blocked reason on the row', async () => {
  const [bar, css] = await Promise.all([
    read('../src/shell/StepBar.tsx'),
    read('../src/styles/simulation-guide.css'),
  ]);
  assert.match(bar, /step-reason/);
  assert.match(bar, /step-here/);
  assert.match(bar, /deriveNextAction/);
  assert.match(bar, /kind === 'none'|next\.kind === 'none'|next === null/);
  assert.match(bar, /onRunCommand\('validate'\)/);
  assert.match(bar, /onRunCommand\('preview-run'\)/);
  assert.match(bar, /onRunCommand\('open-run'\)/);
  assert.match(bar, /onSelectView\('results'\)/);
  assert.match(bar, /act: onNewCase|onNewCase\(\)/);
  assert.match(bar, /activeView === 'results'/);
  assert.match(css, /\.step-bar-main\s*\{[^}]*height:\s*48px/s);
  assert.match(css, /\.step-reason\s*\{[^}]*white-space:\s*nowrap/s);
  assert.match(css, /\.step-num\s*\{[^}]*font-family:\s*var\(--font-mono\)/s);
  assert.doesNotMatch(bar, /from ['"]react-router|from ['"]@mui|new framework/i);
});

test('step guide copy is plain ko and en', async () => {
  const keys = [
    'stepbar.blockedNoTab',
    'stepbar.blockedNoWorkspace',
    'stepbar.blockedRunning',
    'stepbar.next.openWorkspace',
    'stepbar.next.openRun',
    'stepbar.next.run',
    'stepbar.next.results',
    'stepbar.status.current',
  ];
  for (const key of keys) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.notEqual(ko, key, key);
    assert.notEqual(en, key, key);
    assert.doesNotMatch(en, /[가-힣]/, key);
  }
  assert.equal(translate('ko', 'stepbar.blockedNoTab'), '유체 표가 없어요');
  assert.equal(translate('ko', 'stepbar.next.validate'), '검증 실행');
  assert.equal(translate('ko', 'stepbar.next.run'), '실행 미리보기');
  assert.equal(translate('ko', 'stepbar.next.results'), '결과 열기');
  assert.equal(translate('ko', 'stepbar.next.createFluid'), '유체 표 만들기');
  assert.equal(translate('ko', 'stepbar.status.current'), '지금 여기');
  assert.match(translate('ko', 'stepbar.blockedErrors', { count: 2 }), /2/);
});
