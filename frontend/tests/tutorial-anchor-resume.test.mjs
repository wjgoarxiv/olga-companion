import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';
import {
  TUTORIAL_STEPS,
  initialTutorialState,
  pauseTutorial,
  resolveTourTarget,
  resumeChipPending,
  startTutorial,
  tourTargetSelectors,
} from '../src/tutorialTour.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// A tiny stand-in for the DOM: `present` maps a selector to an element-like.
function fakeQuery(present) {
  return (selector) => present[selector] ?? null;
}

test('H-02 step 7 falls back to ringing the Results rail button when the graph is closed', () => {
  const railButton = { name: 'results-button' };
  const railIcon = { name: 'results-icon', closest: (tag) => (tag === 'button' ? railButton : null) };
  const found = resolveTourTarget('result-graph', fakeQuery({ '[data-view="results"]': railIcon }));
  assert.equal(found, railButton, 'the button wrapping the rail icon is the anchor, not the icon span');
});

test('H-02 the real target wins over the fallback when it exists', () => {
  const chart = { name: 'chart' };
  const railIcon = { closest: () => ({ name: 'results-button' }) };
  const found = resolveTourTarget('result-graph', fakeQuery({
    '[data-tour="result-graph"]': chart,
    '[data-view="results"]': railIcon,
  }));
  assert.equal(found, chart);
});

test('H-02 a zero-size primary target is skipped for the fallback', () => {
  const hidden = { name: 'hidden', empty: true };
  const railButton = { name: 'results-button', empty: false };
  const railIcon = { empty: false, closest: () => railButton };
  const found = resolveTourTarget(
    'result-graph',
    fakeQuery({ '[data-tour="result-graph"]': hidden, '[data-view="results"]': railIcon }),
    (element) => !element.empty,
  );
  assert.equal(found, railButton);
});

test('H-02 only step 7 has a fallback; other missing targets stay unanchored', () => {
  for (const step of TUTORIAL_STEPS) {
    const selectors = tourTargetSelectors(step.target);
    assert.equal(selectors[0], `[data-tour="${step.target}"]`);
    assert.equal(selectors.length, step.id === 'result-graph' ? 2 : 1, `fallback count for ${step.id}`);
    if (step.id !== 'result-graph') assert.equal(resolveTourTarget(step.target, fakeQuery({})), null);
  }
  assert.equal(TUTORIAL_STEPS.length, 7);
});

test('M-22 a persisted active tour waits behind a resume chip until acknowledged', () => {
  const active = startTutorial(initialTutorialState());
  assert.equal(resumeChipPending(active, false), true, 'cold start with an active tour shows the chip');
  assert.equal(resumeChipPending(active, true), false, 'after the user resumes the chip is gone');
  assert.equal(resumeChipPending(initialTutorialState(), false), false, 'idle shows the welcome card instead');
  assert.equal(resumeChipPending(pauseTutorial(active), false), false, 'paused tours stay quiet');
});

test('M-22 the host gates the bubble on the chip and acknowledges on user actions', async () => {
  const host = await read('../src/TutorialHost.tsx');
  assert.match(host, /resumeChipPending\(/, 'host asks the pure helper');
  assert.match(host, /useState<boolean>\(\(\) => loadTutorialState\(\)\.status !== 'active'\)|useState\(\(\) => loadTutorialState\(\)\.status !== 'active'\)/,
    'launch state is read once from storage');
  assert.match(host, /<TutorialResumeChip/, 'chip is rendered');
  assert.match(host, /step !== null && !chipPending/, 'bubble is hidden while the chip is pending');
  const spotlight = await read('../src/TutorialSpotlight.tsx');
  assert.match(spotlight, /export function TutorialResumeChip/, 'chip lives next to the spotlight');
  assert.match(spotlight, /\.tutorial-btn/, 'chip anchors to the title bar tutorial button');
  assert.match(spotlight, /resolveTourTarget\(/, 'spotlight resolves the target with the fallback');
});

test('M-22 resume copy resolves in ko and en', () => {
  assert.match(translate('ko', 'tutorial.resume', { n: 7 }), /7/);
  const en = translate('en', 'tutorial.resume', { n: 7 });
  assert.match(en, /7/);
  assert.doesNotMatch(en, /[가-힣]/);
  assert.notEqual(translate('ko', 'tutorial.resume', { n: 7 }), 'tutorial.resume');
});

test('M-22 the chip is a small anchored control, not a veil', async () => {
  const css = await read('../src/styles/tutorial.css');
  const chip = /\.tutorial-resume\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
  assert.match(chip, /position:\s*fixed/);
  assert.match(chip, /pointer-events:\s*auto/);
  assert.doesNotMatch(chip, /box-shadow|border-radius:\s*\d{2,}px/, 'no shadow or pill radius');
});

test('H-19 the endcard takes focus, closes on Escape and returns focus', async () => {
  const host = await read('../src/TutorialHost.tsx');
  assert.match(host, /function TutorialEndCard/, 'endcard is its own component');
  const card = host.slice(host.indexOf('function TutorialEndCard'));
  assert.match(card, /\.focus\(/, 'focuses itself on mount');
  assert.match(card, /event\.key === 'Escape'/, 'handles Escape');
  assert.match(card, /scheduleFocusReturn\(/, 'returns focus on close');
  assert.match(card, /\.tutorial-btn/, 'falls back to the title bar tutorial button');
  assert.match(card, /role="dialog"/);
});
