import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const overviewSource = await readFile(
  new URL('../src/RunViewOverview.tsx', import.meta.url),
  'utf8',
);

test('empty Run directs the operator to case selection without contradicting model state', () => {
  assert.match(
    overviewSource,
    /t\('run\.openWorkspace'\)[\s\S]*?t\('run\.emptyNote'\)/,
    'the empty-state action and guidance describe the same next step',
  );
  assert.doesNotMatch(
    overviewSource,
    /Choose the model first/,
    'the Run view must not request model selection when model identity is already available',
  );
});
