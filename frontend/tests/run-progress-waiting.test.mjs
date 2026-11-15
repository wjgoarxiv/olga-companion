import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

/* Bug report 2026-11-15 (0.1.8): right after a run started, the progress line read
 * "솔버가 진행률을 보고하지 않음", which looked like an error. Before the first report
 * it now says it is waiting; "not reported" is kept for a finished run. */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('a running solver without a percentage yet reads as waiting', async () => {
  const source = await read('../src/RunProgress.tsx');
  assert.match(source, /finished \|\| supervisionUnknown \? t\('run\.noVendor'\) : t\('run\.vendorWaiting'\)/);
  for (const locale of ['ko', 'en']) {
    assert.match(await read(`../src/i18n/${locale}.ts`), /'run\.vendorWaiting': '/);
  }
});

test('a failed preview lists what the validator found', async () => {
  const source = await read('../src/RunSingleCasePanel.tsx');
  assert.match(source, /preview\.validation\.problems\?\.map/);
  for (const locale of ['ko', 'en']) {
    assert.match(await read(`../src/i18n/${locale}.ts`), /'run\.validatorProblems': '/);
  }
});
