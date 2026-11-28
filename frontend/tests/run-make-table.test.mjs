// Owner decision 2026-11-17 (A): a missing .tab is made from an .mfl next to the case by the Multiflash engine.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { makeableName } from '../src/companionCopyRules.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('only a plain .tab name next to the case can be made', () => {
  assert.equal(makeableName('air_water.tab'), 'air_water.tab');
  assert.equal(makeableName('.\\air.TAB'), 'air.TAB');
  for (const bad of ['', 'fluids/air.tab', '../air.tab', 'C:\\air.tab', '/abs/air.tab', 'restart.rst']) {
    assert.equal(makeableName(bad), null, bad);
  }
});

test('each missing reference also gets a make-table control in the run panel', async () => {
  const panel = await read('../src/RunSingleCasePanel.tsx');
  assert.match(panel, /import \{ MakeTableControl \} from '\.\/MakeTableControl'/);
  assert.match(panel, /<MakeTableControl[\s\S]*source=\{preview\.source\}[\s\S]*reference=\{reference\}[\s\S]*onPreviewAgain=\{doPreview\}/);
});

test('the table is made only after an explicit approve click and no run starts', async () => {
  const control = await read('../src/MakeTableControl.tsx');
  const api = await read('../src/makeTableApi.ts');
  assert.match(control, /onClick=\{approve\}/);
  assert.equal((control.match(/makeTable\(/g) ?? []).length, 1);
  assert.match(control, /async function approve\(\)[\s\S]*makeTable\(/);
  assert.doesNotMatch(control, /runExecute|doRun|onPreviewAgain\(\);/);
  assert.match(control, /onClick=\{onPreviewAgain\}/);
  assert.match(api, /\/api\/fluids\/make-tab\/candidates/);
  assert.match(api, /\/api\/fluids\/make-tab'[\s\S]*approved: true/);
});

test('the wording exists in English and Korean', async () => {
  for (const file of ['../src/i18n/en.ts', '../src/i18n/ko.ts']) {
    const text = await read(file);
    for (const key of ['run.makeTable', 'run.makeTableConfirm', 'run.makeTableApprove', 'run.makeTableBusy', 'run.makeTableDone', 'run.makeTableDefaultGrid', 'run.makeTableWarning']) {
      assert.match(text, new RegExp(`'${key.replace('.', '\\.')}':`), `${file} ${key}`);
    }
  }
});

test('engine warnings use the UI language for their label and never collide as React keys', async () => {
  // Review 2026-11-27: the prefix was hard-coded English and the text itself was the key.
  const control = await read('../src/MakeTableControl.tsx');
  assert.doesNotMatch(control, />Multiflash: \{/);
  assert.match(control, /engine_warnings[\s\S]*\.map\(\(text, index\) =>[\s\S]*key=\{index\}[\s\S]*t\('run\.makeTableWarning', \{ text \}\)/);
});
