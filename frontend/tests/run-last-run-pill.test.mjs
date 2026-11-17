import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';

// Live PVT (lane A): a finished run restored from history showed the pill "준비됨"
// with only "먼저 미리보기", so the user could not tell a run had already ended.
test('a run restored from history names how it ended, in the pill and in a hint', async () => {
  const panel = await readFile(new URL('../src/RunSingleCasePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /statusSource === 'history'/);
  assert.match(panel, /t\('run\.lastRunPill'/);
  assert.match(panel, /lastRun && <p className="run-hint run-last-hint">\{t\('run\.lastRunHint'/);
  for (const dict of [ko, en]) {
    assert.match(dict['run.lastRunPill'], /\{state\}/);
    assert.match(dict['run.lastRunHint'], /\{state\}/);
  }
});
