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

// Security review B1/C1: network paths in a shared case are named as not used.
test('the run preview says network paths are not used', async () => {
  const panel = await readFile(new URL('../src/RunSingleCasePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /preview\.companions_network\?\.length \?\? 0\) > 0 && <p className="run-hint">\{t\('run\.companionsNetwork'\)\}<\/p>/);
  const contracts = await readFile(new URL('../src/runContracts.ts', import.meta.url), 'utf8');
  assert.match(contracts, /companions_network\?: readonly string\[\]/);
  const en = await readFile(new URL('../src/i18n/en.ts', import.meta.url), 'utf8');
  const ko = await readFile(new URL('../src/i18n/ko.ts', import.meta.url), 'utf8');
  assert.match(en, /'run\.companionsNetwork': 'Network paths/);
  assert.match(ko, /'run\.companionsNetwork': '네트워크 경로/);
});
