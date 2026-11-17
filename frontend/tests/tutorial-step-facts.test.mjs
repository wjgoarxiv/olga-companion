import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { freshRunIds, tutorialStepSatisfied } from '../src/tutorialTour.mjs';

const installed = 'air_water_horizontal_2.genkey';

function facts(overrides = {}) {
  return {
    workspaceRoot: '/tmp/ws',
    activeCaseName: installed,
    installedCaseName: installed,
    validatedCaseName: null,
    validationOk: false,
    validationRead: false,
    runStartedForCase: false,
    runFinishedForCase: false,
    resultsOpenedForCase: false,
    ...overrides,
  };
}

test('demo step completes only for the installed case name', () => {
  assert.equal(tutorialStepSatisfied('demo-case', facts()), true);
  assert.equal(tutorialStepSatisfied('demo-case', facts({ activeCaseName: 'other.genkey' })), false);
  assert.equal(tutorialStepSatisfied('demo-case', facts({ installedCaseName: '' })), false);
});

test('validate and results ignore a different active case', () => {
  assert.equal(tutorialStepSatisfied('validate', facts({
    validatedCaseName: installed,
    validationOk: true,
    activeCaseName: 'other.genkey',
  })), false);
  assert.equal(tutorialStepSatisfied('validate', facts({
    validatedCaseName: installed,
    validationOk: true,
  })), true);
  assert.equal(tutorialStepSatisfied('result-graph', facts({
    resultsOpenedForCase: true,
    activeCaseName: 'other.genkey',
  })), false);
  assert.equal(tutorialStepSatisfied('result-graph', facts({ resultsOpenedForCase: true })), true);
});

test('a run that was already in the timeline does not finish the run step', () => {
  const baseline = new Set(['old-run']);
  assert.deepEqual(freshRunIds(['old-run'], baseline), []);
  assert.deepEqual(freshRunIds(['old-run', 'new-run'], baseline), ['new-run']);
  assert.equal(tutorialStepSatisfied('run', facts({ runStartedForCase: false })), false);
  assert.equal(tutorialStepSatisfied('run', facts({ runStartedForCase: true, activeCaseName: 'other.genkey' })), false);
  assert.equal(tutorialStepSatisfied('run', facts({ runStartedForCase: true })), true);
  assert.equal(tutorialStepSatisfied('run-progress', facts({ runFinishedForCase: false })), false);
  assert.equal(tutorialStepSatisfied('run-progress', facts({ runFinishedForCase: true })), true);
});

test('reading validation needs the installed case and an explicit read when the panel was already open', () => {
  assert.equal(tutorialStepSatisfied('validation-result', facts({
    validatedCaseName: installed,
    validationOk: true,
    validationRead: false,
  })), false);
  assert.equal(tutorialStepSatisfied('validation-result', facts({
    validatedCaseName: 'other.genkey',
    validationOk: true,
    validationRead: true,
  })), false);
  assert.equal(tutorialStepSatisfied('validation-result', facts({
    validatedCaseName: installed,
    validationOk: true,
    validationRead: true,
  })), true);
});

test('the demo step installs the bundled example instead of pasting the chat draft', () => {
  const host = readFileSync(new URL('../src/TutorialHost.tsx', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const gallery = readFileSync(new URL('../src/ExampleGallery.tsx', import.meta.url), 'utf8');
  assert.match(host, /installExample\(DEMO_EXAMPLE_ID\)/);
  assert.doesNotMatch(host, /onDraft\(t\('tutorial\.demoDraft'\)\)/);
  assert.match(app, /applyTutorialCommand\(kind,/);
  assert.doesNotMatch(app, /tutorial\.demoDraft/);
  assert.match(gallery, /data-tour="demo-case"/);
  assert.match(gallery, /t\('examples\.start'\)/);
});
