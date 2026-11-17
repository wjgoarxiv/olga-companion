import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Owner report 2026-11-16: a .tab outside the case folder only failed after approval.
test('the run preview names referenced files the run will not find, before approval', async () => {
  const panel = await readFile(new URL('../src/RunSingleCasePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /preview\.companions_missing\?\.map/);
  assert.match(panel, /run-preview-problems" role="alert"[\s\S]*run\.companionsMissingHint/);
  const contracts = await readFile(new URL('../src/runContracts.ts', import.meta.url), 'utf8');
  assert.match(contracts, /companions_missing\?: readonly string\[\]/);
});
