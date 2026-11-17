import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { referenceIsCopyable } from '../src/companionCopyRules.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// Owner decision 2026-11-16 (B): fix a missing .tab by an approval-gated copy next to the case.
test('only a relative .tab name inside the case folder offers a copy', () => {
  assert.equal(referenceIsCopyable('air_water.tab'), true);
  assert.equal(referenceIsCopyable('fluids/deep/air_water.TAB'), true);
  assert.equal(referenceIsCopyable('.\\fluids\\air.tab'), true);
  for (const bad of ['', '../x/air.tab', 'a/../../air.tab', '/abs/air.tab', 'C:\\fluids\\air.tab', 'restart.rst', 'fluids/']) {
    assert.equal(referenceIsCopyable(bad), false, bad);
  }
});

test('each missing reference gets a copy control inside the run panel', async () => {
  const panel = await read('../src/RunSingleCasePanel.tsx');
  assert.match(panel, /import \{ CompanionCopyControl \} from '\.\/CompanionCopyControl'/);
  assert.match(panel, /<CompanionCopyControl[\s\S]*source=\{preview\.source\}[\s\S]*reference=\{reference\}[\s\S]*onPreviewAgain=\{doPreview\}/);
});

test('the control copies only after an explicit approve click and never starts a run', async () => {
  const control = await read('../src/CompanionCopyControl.tsx');
  const api = await read('../src/companionCopyApi.ts');
  // Review first (read-only), then a separate approve click performs the copy.
  assert.match(control, /companionCopyPreview\(/);
  assert.match(control, /onClick=\{approve\}/);
  assert.equal((control.match(/companionCopyApproved\(/g) ?? []).length, 1);
  assert.match(control, /async function approve\(\)[\s\S]*companionCopyApproved\(/);
  assert.doesNotMatch(control, /runExecute|doRun|onPreviewAgain\(\);/);
  // After the copy the user is asked to preview again, with their own click.
  assert.match(control, /run\.companionCopyDone/);
  assert.match(control, /onClick=\{onPreviewAgain\}/);
  assert.match(api, /companion-copy\/preview[\s\S]*body\(request, false\)/);
  assert.match(api, /companion-copy\/execute[\s\S]*body\(request, true, reviewed\)/);
  assert.match(api, /\/api\/run\/companion-copy\/execute/);
  // The approval is bound to the previewed bytes: the reviewed sha256 and size travel with the execute call.
  assert.match(control, /companionCopyApproved\(request, \{ sha256: reviewed\.sha256, size: reviewed\.size \}\)/);
  assert.match(api, /sha256: reviewed\.sha256, size: reviewed\.size/);
  assert.match(api, /\/api\/run\/companion-copy\/preview/);
  assert.match(control, /fetchWorkspace\(\)/);
  assert.match(control, /suffix === '\.tab'/);
});

test('every copy string exists in English and Korean and differs between them', async () => {
  const en = await read('../src/i18n/en.ts');
  const ko = await read('../src/i18n/ko.ts');
  const control = await read('../src/CompanionCopyControl.tsx');
  const keys = [...new Set([...control.matchAll(/'(run\.companionCopy[A-Za-z]*)'/g)].map((match) => match[1]))];
  assert.ok(keys.length >= 8, keys.join(','));
  for (const key of keys) {
    const pattern = new RegExp(`'${key}':\\s*(?:'((?:[^'\\\\]|\\\\.)*)'|\`([^\`]*)\`)`);
    const enMatch = en.match(pattern);
    const koMatch = ko.match(pattern);
    assert.ok(enMatch, `en ${key}`);
    assert.ok(koMatch, `ko ${key}`);
    assert.notEqual(enMatch[1] ?? enMatch[2], koMatch[1] ?? koMatch[2], key);
  }
});
