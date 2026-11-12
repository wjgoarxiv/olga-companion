import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
import {
  TUTORIAL_EVENTS,
  TUTORIAL_STEPS,
  TUTORIAL_STORAGE_KEY,
  advanceTutorial,
  initialTutorialState,
  isTutorialFinished,
  loadTutorialState,
  pauseTutorial,
  resetTutorial,
  resumeTutorial,
  saveTutorialState,
  skipTutorial,
  startTutorial,
} from '../src/tutorialTour.mjs';

function memoryStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)); },
  };
}

const ORDERED_EVENTS = [
  TUTORIAL_EVENTS.WORKSPACE_CHOSEN,
  TUTORIAL_EVENTS.CASE_CREATED,
  TUTORIAL_EVENTS.VALIDATION_DONE,
  TUTORIAL_EVENTS.VALIDATION_READ,
  TUTORIAL_EVENTS.RUN_STARTED,
  TUTORIAL_EVENTS.RUN_FINISHED,
  TUTORIAL_EVENTS.RESULTS_OPENED,
];

test('T7 tour: seven steps in case order with data-tour targets and copy keys', async () => {
  assert.equal(TUTORIAL_STEPS.length, 7);
  assert.deepEqual(
    TUTORIAL_STEPS.map((step) => step.id),
    ['workspace', 'demo-case', 'validate', 'validation-result', 'run', 'run-progress', 'result-graph'],
  );
  assert.deepEqual(
    TUTORIAL_STEPS.map((step) => step.target),
    ['workspace', 'demo-case', 'validate', 'validation-result', 'run', 'run-progress', 'result-graph'],
  );
  assert.deepEqual(
    TUTORIAL_STEPS.map((step) => step.event),
    ORDERED_EVENTS,
  );
  for (const step of TUTORIAL_STEPS) {
    assert.match(step.target, /^[a-z-]+$/, `target for ${step.id} is a data-tour value`);
    assert.notEqual(translate('ko', `${step.textKey}.title`), `${step.textKey}.title`);
    assert.notEqual(translate('ko', `${step.textKey}.body`), `${step.textKey}.body`);
    const enTitle = translate('en', `${step.textKey}.title`);
    assert.notEqual(enTitle, `${step.textKey}.title`);
    assert.doesNotMatch(enTitle, /[가-힣]/, `en title for ${step.id} carries no Hangul`);
  }
});

test('T7 tour: advances only on the current step event, in order', async () => {
  let state = startTutorial(initialTutorialState());
  assert.equal(state.index, 0);
  assert.equal(advanceTutorial(state, TUTORIAL_EVENTS.RUN_STARTED).index, 0);
  assert.equal(advanceTutorial(state, TUTORIAL_EVENTS.RESULTS_OPENED).index, 0);
  for (const [position, event] of ORDERED_EVENTS.entries()) {
    state = advanceTutorial(state, event);
    assert.equal(state.index, position + 1, `event ${event} completes step ${position + 1}`);
    assert.equal(state.status, position === 6 ? 'done' : 'active');
  }
  assert.ok(isTutorialFinished(state));
  assert.deepEqual(advanceTutorial(state, TUTORIAL_EVENTS.WORKSPACE_CHOSEN), state);
});

test('T7 tour: skip pauses later resume and replay restart the tour', async () => {
  const storage = memoryStorage();
  let state = startTutorial(initialTutorialState());
  state = advanceTutorial(state, TUTORIAL_EVENTS.WORKSPACE_CHOSEN);
  assert.equal(state.index, 1);
  const paused = pauseTutorial(state);
  assert.equal(paused.status, 'paused');
  assert.equal(paused.index, 1);
  assert.equal(advanceTutorial(paused, TUTORIAL_EVENTS.CASE_CREATED).index, 1);
  const resumed = resumeTutorial(paused);
  assert.equal(resumed.status, 'active');
  assert.equal(advanceTutorial(resumed, TUTORIAL_EVENTS.CASE_CREATED).index, 2);
  const skipped = skipTutorial(resumed);
  assert.equal(skipped.status, 'skipped');
  assert.ok(isTutorialFinished(skipped));
  assert.equal(advanceTutorial(skipped, TUTORIAL_EVENTS.VALIDATION_DONE).status, 'skipped');
  saveTutorialState(skipped, storage);
  assert.ok(isTutorialFinished(loadTutorialState(storage)));
  const replayed = resetTutorial(loadTutorialState(storage));
  assert.equal(replayed.status, 'active');
  assert.equal(replayed.index, 0);
});

test('T7 tour: no-OLGA branch ends the run step gracefully', async () => {
  let state = startTutorial(initialTutorialState());
  for (const event of ORDERED_EVENTS.slice(0, 4)) state = advanceTutorial(state, event);
  assert.equal(state.index, 4);
  // NO_OLGA anywhere else is ignored.
  assert.equal(advanceTutorial(initialTutorialState(), TUTORIAL_EVENTS.NO_OLGA).index, 0);
  const finished = advanceTutorial(state, TUTORIAL_EVENTS.NO_OLGA);
  assert.equal(finished.status, 'done');
  assert.equal(finished.finishedWithoutOlga, true);
  assert.ok(isTutorialFinished(finished));
  assert.notEqual(translate('ko', 'tutorial.noOlga.body'), 'tutorial.noOlga.body');
});

test('T7 tour: progress persists across loads and unknown payloads reset safely', async () => {
  const storage = memoryStorage();
  assert.equal(loadTutorialState(storage).status, 'idle');
  let state = startTutorial(initialTutorialState());
  state = advanceTutorial(state, TUTORIAL_EVENTS.WORKSPACE_CHOSEN);
  saveTutorialState(state, storage);
  const restored = loadTutorialState(storage);
  assert.equal(restored.status, 'active');
  assert.equal(restored.index, 1);
  storage.setItem(TUTORIAL_STORAGE_KEY, 'not-json{{{');
  assert.equal(loadTutorialState(storage).status, 'idle');
});

test('T7 tour: shell chrome copy resolves in ko+en without hardcoded text', async () => {
  for (const key of [
    'tutorial.button', 'tutorial.replay', 'tutorial.end', 'tutorial.later',
    'tutorial.start', 'tutorial.progress', 'tutorial.useDemo', 'tutorial.demoDraft',
    'tutorial.welcome.title', 'tutorial.welcome.body',
    'tutorial.done.title', 'tutorial.done.body',
    'tutorial.done.example1', 'tutorial.done.example2',
  ]) {
    assert.notEqual(translate('ko', key), key, `${key} resolves in ko`);
    const en = translate('en', key);
    assert.notEqual(en, key, `${key} resolves in en`);
    assert.doesNotMatch(en, /[가-힣]/, `${key} en carries no Hangul`);
  }
  assert.match(translate('ko', 'tutorial.progress', { n: 3 }), /3/);
});

test('T7 QA: veil dims like the overlay scrim, dot takes its own space', async () => {
  const css = await read('../src/styles/tutorial.css');
  const veil = /\.tutorial-veil\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
  assert.match(veil, /var\(--bg-deep\)/, 'veil uses the dark scrim token');
  assert.doesNotMatch(veil, /rgb\(|#[0-9a-fA-F]/, 'veil has no colour literal');
  const dot = /\.tutorial-dot\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
  assert.doesNotMatch(dot, /position:\s*absolute/, 'dot is not overlaid on the text');
  assert.match(dot, /margin-inline-start/, 'dot takes its own space after the label');
});

test('T7 QA: the end label is explicit and boot gates the host', async () => {
  assert.equal(translate('ko', 'tutorial.end'), '튜토리얼 끝내기');
  assert.equal(translate('en', 'tutorial.end'), 'End tutorial');
  const host = await read('../src/TutorialHost.tsx');
  assert.match(host, /ready/, 'host takes a boot-ready gate');
  assert.match(host, /if\s*\(!ready\)\s*return null/, 'host renders nothing before boot is ready');
  const app = await read('../src/App.tsx');
  assert.match(app, /<TutorialHost[^>]*ready=\{runtime\.state === 'online'\}/, 'mount passes runtime online as ready');
});
