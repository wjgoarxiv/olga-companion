import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('lnfit stepbar: open Results never offers Open results as Next', async () => {
  const src = await read('../src/shell/StepBar.tsx');
  assert.match(src, /activeView|currentView|view\b.*results|results.*view/i, 'StepBar knows the open view');
  assert.match(src, /stepbar\.next\.edit/, 'the follow-up reuses the existing edit copy');
  assert.match(src, /activeView.*results|results.*activeView/i, 'the results-open case is branched');
});
