import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import {
  TUTORIAL_EVENTS,
  TUTORIAL_STEPS,
  TUTORIAL_STORAGE_KEY,
  advanceTutorial,
  initialTutorialState,
  loadTutorialState,
  pauseTutorial,
  resetTutorial,
  resumeTutorial,
  saveTutorialState,
  setTutorialPath,
  skipTutorial,
  startTutorial,
  stepAction,
  tutorialStepSatisfied,
  tutorialSteps,
} from '../src/tutorialTour.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function memoryStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)); },
  };
}

test('the demo path is the unchanged seven steps; the pipe path swaps only steps 2 and 7', () => {
  assert.equal(tutorialSteps('demo'), TUTORIAL_STEPS);
  assert.equal(tutorialSteps(undefined), TUTORIAL_STEPS);
  const pipe = tutorialSteps('pipe');
  assert.equal(pipe.length, 7);
  assert.deepEqual(pipe.map((step) => step.id),
    ['workspace', 'pipe-case', 'validate', 'validation-result', 'run', 'run-progress', 'result-flow']);
  assert.deepEqual(pipe.map((step) => step.event), TUTORIAL_STEPS.map((step) => step.event),
    'same events in the same order, so skip/resume/advance logic is shared');
  for (const index of [0, 2, 3, 4, 5]) assert.equal(pipe[index], TUTORIAL_STEPS[index]);
});

test('every step on both paths says why, where and what is done, in ko and en', () => {
  const ids = new Set([...TUTORIAL_STEPS, ...tutorialSteps('pipe')].map((step) => step.id));
  assert.equal(ids.size, 9);
  for (const step of [...TUTORIAL_STEPS, ...tutorialSteps('pipe')]) {
    for (const part of ['title', 'body', 'where', 'done']) {
      const key = `${step.textKey}.${part}`;
      assert.ok(ko[key], `${key} in ko`);
      assert.ok(en[key], `${key} in en`);
      assert.notEqual(ko[key], en[key], `${key} ko differs from en`);
      assert.doesNotMatch(en[key], /[가-힣]/, `${key} en has no Hangul`);
    }
    assert.doesNotMatch(ko[`${step.textKey}.title`], /케이스/);
    assert.doesNotMatch(ko[`${step.textKey}.body`], /\n/, 'why is a single line');
  }
});

test('each step quotes the step-bar status line by key, never its own wording', async () => {
  const stepState = await read('../src/shell/useStepState.ts');
  for (const step of [...TUTORIAL_STEPS, ...tutorialSteps('pipe')]) {
    assert.match(step.statusKey, /^stepbar\.line\./, `${step.id} uses a stepbar.line key`);
    assert.ok(ko[step.statusKey] && en[step.statusKey], `${step.statusKey} exists`);
    assert.ok(stepState.includes(`'${step.statusKey}'`), `${step.statusKey} is emitted by deriveStatusLine`);
  }
  const spotlight = await read('../src/TutorialSpotlight.tsx');
  assert.match(spotlight, /statusLine/);
  assert.match(spotlight, /\.where'|\.where`/);
  assert.match(spotlight, /\.done`|\.done'/);
});

test('the path choice is stored, defaults to demo, and only changes before the case step is done', () => {
  const idle = initialTutorialState();
  assert.equal(idle.path, 'demo');
  const pipe = setTutorialPath(startTutorial(idle), 'pipe');
  assert.equal(pipe.path, 'pipe');
  assert.equal(pipe.status, 'active');
  assert.equal(setTutorialPath(pipe, 'bogus').path, 'pipe');
  const second = advanceTutorial(pipe, TUTORIAL_EVENTS.WORKSPACE_CHOSEN);
  assert.equal(second.index, 1);
  assert.equal(setTutorialPath(second, 'demo').path, 'demo', 'can still switch while the case step is open');
  const third = advanceTutorial(second, TUTORIAL_EVENTS.CASE_CREATED);
  assert.equal(setTutorialPath(third, 'demo').path, 'pipe', 'locked once the case exists');
});

test('a tour saved before paths existed loads as the demo path', () => {
  const storage = memoryStorage();
  storage.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify({ version: 1, status: 'active', index: 3, finishedWithoutOlga: false }));
  const loaded = loadTutorialState(storage);
  assert.equal(loaded.path, 'demo');
  assert.equal(loaded.index, 3);
  storage.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify({ version: 1, status: 'active', index: 1, finishedWithoutOlga: false, path: 'x' }));
  assert.equal(loadTutorialState(storage).path, 'demo');
});

test('skip, pause, resume and resume-after-reload keep the chosen path and index', () => {
  const storage = memoryStorage();
  let state = setTutorialPath(startTutorial(initialTutorialState()), 'pipe');
  state = advanceTutorial(state, TUTORIAL_EVENTS.WORKSPACE_CHOSEN);
  const paused = pauseTutorial(state);
  assert.equal(paused.path, 'pipe');
  assert.equal(advanceTutorial(paused, TUTORIAL_EVENTS.CASE_CREATED).index, 1, 'paused does not advance');
  const resumed = resumeTutorial(paused);
  assert.equal(resumed.path, 'pipe');
  saveTutorialState(resumed, storage);
  const reloaded = loadTutorialState(storage);
  assert.equal(reloaded.path, 'pipe');
  assert.equal(reloaded.index, 1);
  assert.equal(reloaded.status, 'active');
  assert.equal(advanceTutorial(reloaded, TUTORIAL_EVENTS.CASE_CREATED).index, 2);
  const skipped = skipTutorial(reloaded);
  assert.equal(skipped.status, 'skipped');
  assert.equal(skipped.path, 'pipe');
  assert.equal(resetTutorial(skipped).path, 'pipe', 'replay keeps the path; the first bubble lets the user switch');
  assert.equal(resetTutorial(skipped).index, 0);
});

test('the pipe path walks all seven events and ends done', () => {
  let state = setTutorialPath(startTutorial(initialTutorialState()), 'pipe');
  for (const step of tutorialSteps('pipe')) state = advanceTutorial(state, step.event);
  assert.equal(state.status, 'done');
  assert.equal(state.path, 'pipe');
});

test('no OLGA still ends the pipe path at the run step', () => {
  let state = setTutorialPath(startTutorial(initialTutorialState()), 'pipe');
  for (const event of [TUTORIAL_EVENTS.WORKSPACE_CHOSEN, TUTORIAL_EVENTS.CASE_CREATED, TUTORIAL_EVENTS.VALIDATION_DONE, TUTORIAL_EVENTS.VALIDATION_READ]) {
    state = advanceTutorial(state, event);
  }
  const finished = advanceTutorial(state, TUTORIAL_EVENTS.NO_OLGA);
  assert.equal(finished.status, 'done');
  assert.equal(finished.finishedWithoutOlga, true);
});

test('pipe steps: the wizard step opens the wizard, the last step opens results; both need the tour case', () => {
  assert.deepEqual(stepAction('pipe-case'), { kind: 'open-pipe-wizard', labelKey: 'tutorial.action.openPipeWizard' });
  assert.deepEqual(stepAction('result-flow'), { kind: 'open-results', labelKey: 'tutorial.action.openFlow' });
  const facts = (extra) => ({
    workspaceRoot: '/ws', activeCaseName: 'a.genkey', installedCaseName: 'a.genkey', ...extra,
  });
  assert.equal(tutorialStepSatisfied('pipe-case', facts({})), true);
  assert.equal(tutorialStepSatisfied('pipe-case', facts({ activeCaseName: 'b.genkey' })), false);
  assert.equal(tutorialStepSatisfied('pipe-case', facts({ installedCaseName: '' })), false);
  assert.equal(tutorialStepSatisfied('result-flow', facts({ resultsOpenedForCase: true })), true);
  assert.equal(tutorialStepSatisfied('result-flow', facts({ resultsOpenedForCase: true, activeCaseName: 'b.genkey' })), false);
  assert.ok(ko['tutorial.action.openPipeWizard'] && en['tutorial.action.openPipeWizard']);
  assert.ok(ko['tutorial.action.openFlow'] && en['tutorial.action.openFlow']);
});

test('the welcome card offers the two starts and the first bubble lets the user switch', async () => {
  const welcome = await read('../src/WelcomeCard.tsx');
  assert.match(welcome, /tutorial\.path\.demo/);
  assert.match(welcome, /tutorial\.path\.pipe/);
  assert.match(welcome, /onStart: \(path|onStart\(['"]demo['"]\)/);
  assert.match(welcome, /onStart\(['"]pipe['"]\)/);
  const spotlight = await read('../src/TutorialSpotlight.tsx');
  assert.match(spotlight, /onChoosePath/);
  assert.match(spotlight, /aria-pressed/);
  const host = await read('../src/TutorialHost.tsx');
  assert.match(host, /tutorialSteps\(tutorial\.path\)/);
  assert.match(host, /setTutorialPath\(/);
  assert.match(host, /requestPipeTableWizard\(\)/);
  assert.match(host, /open-pipe-wizard/);
  for (const key of ['tutorial.path.demo', 'tutorial.path.pipe', 'tutorial.path.label', 'tutorial.path.demoHint', 'tutorial.path.pipeHint',
    'tutorial.label.where', 'tutorial.label.done', 'tutorial.label.status', 'tutorial.caseFallback']) {
    assert.ok(ko[key], `${key} in ko`);
    assert.ok(en[key], `${key} in en`);
    assert.notEqual(ko[key], en[key], `${key} ko differs`);
  }
});

test('choice buttons are real targets: 44px and tokens only', async () => {
  const css = await read('../src/styles/tutorial.css');
  const choice = /\.tutorial-choice\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
  assert.match(choice, /min-height:\s*var\(--tgt\)/);
  assert.doesNotMatch(choice, /#[0-9a-fA-F]{3,6}|rgb\(|animation/);
  assert.match(css, /\.tutorial-choice\[aria-pressed="true"\]/);
  assert.doesNotMatch(css, /infinite/);
});
