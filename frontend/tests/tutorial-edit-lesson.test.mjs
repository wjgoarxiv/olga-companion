// 0.1.20 row 11: one beginner lesson on the demo case: change ENDTIME, review, approve, run, read the result.
import assert from 'node:assert/strict';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import {
  TUTORIAL_EVENTS,
  TUTORIAL_PATHS,
  advanceTutorial,
  initialTutorialState,
  isEditCopyOf,
  loadTutorialState,
  setTutorialPath,
  startTutorial,
  stepAction,
  tutorialStepSatisfied,
  tutorialSteps,
} from '../src/tutorialTour.mjs';

const memory = (value) => ({ getItem: () => JSON.stringify(value), setItem: () => {} });

test('the edit lesson is a third path: demo case, edit and approve, run, watch, result', () => {
  assert.ok(TUTORIAL_PATHS.includes('edit'));
  assert.deepEqual(tutorialSteps('edit').map((step) => step.id),
    ['workspace', 'demo-case', 'edit-endtime', 'run', 'run-progress', 'result-graph']);
  assert.deepEqual(stepAction('edit-endtime'), { kind: 'open-edit', labelKey: 'tutorial.action.openEdit' });
});

test('the edit step is done only when an approved copy of the demo case is the open case', () => {
  assert.equal(isEditCopyOf('demo.edit1.genkey', 'demo.genkey'), true);
  assert.equal(isEditCopyOf('demo.edit12.genkey', 'demo.genkey'), true);
  assert.equal(isEditCopyOf('demo.genkey', 'demo.genkey'), false);
  assert.equal(isEditCopyOf('other.edit1.genkey', 'demo.genkey'), false);
  const facts = (active) => ({ activeCaseName: active, demoCaseName: 'demo.genkey', installedCaseName: active });
  assert.equal(tutorialStepSatisfied('edit-endtime', facts('demo.edit1.genkey')), true);
  assert.equal(tutorialStepSatisfied('edit-endtime', facts('demo.genkey')), false, 'opening the table or reviewing saves nothing');
});

test('the six-step lesson finishes after its last step, not after seven', () => {
  let state = setTutorialPath(startTutorial(initialTutorialState()), 'edit');
  assert.equal(state.path, 'edit');
  const events = tutorialSteps('edit').map((step) => step.event);
  for (const event of events) state = advanceTutorial(state, event);
  assert.equal(state.status, 'done');
});

test('a saved edit lesson resumes on its own path', () => {
  const state = loadTutorialState(memory({ version: 1, status: 'active', index: 2, finishedWithoutOlga: false, path: 'edit' }));
  assert.equal(state.path, 'edit');
  assert.equal(tutorialSteps(state.path)[state.index].id, 'edit-endtime');
  assert.equal(advanceTutorial(state, TUTORIAL_EVENTS.EDIT_SAVED).index, 3);
});

test('every lesson string exists in en and ko', () => {
  const keys = ['tutorial.path.edit', 'tutorial.path.editHint', 'tutorial.action.openEdit',
    ...['title', 'body', 'where', 'done'].map((part) => `tutorial.step.edit-endtime.${part}`)];
  for (const key of keys) {
    assert.ok(en[key], `en ${key}`);
    assert.ok(ko[key], `ko ${key}`);
  }
});

test('the resume chip counts the steps of the lesson it is on', async () => {
  const { reviewNotesRenderer } = await import('./helpers/render-review-notes.mjs');
  const r = await reviewNotesRenderer();
  assert.match(r.renderResumeChip('en', 5, 6), /6 of 6/);
  assert.match(r.renderResumeChip('ko', 2, 7), /3 \/ 7/);
  assert.doesNotMatch(r.renderResumeChip('en', 5, 6), /of 7/);
});
