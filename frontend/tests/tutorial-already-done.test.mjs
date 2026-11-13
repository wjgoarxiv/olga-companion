import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { TUTORIAL_EVENTS, advanceTutorial, initialTutorialState, startTutorial } from '../src/tutorialTour.mjs';

// QA found the tour stuck on step 1 when a workspace was already open: the
// host only re-checked progress when the workspace changed, not when the tour started.
test('the host re-checks finished steps when the tour starts', () => {
  const source = readFileSync(new URL('../src/TutorialHost.tsx', import.meta.url), 'utf8');
  const deps = source.match(/\}, \[([^\]]*workspaceRoot, activeCaseName[^\]]*)\]\);/);
  assert.ok(deps, 'progress effect dependency list found');
  assert.match(deps[1], /tutorial\.status/);
});

test('an already-chosen workspace advances a freshly started tour', () => {
  const started = startTutorial(initialTutorialState());
  const next = advanceTutorial(started, TUTORIAL_EVENTS.WORKSPACE_CHOSEN);
  assert.equal(next.index, started.index + 1);
});
