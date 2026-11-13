import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('runtime panel lists detection and drives pick/clear through the sidecar', async () => {
  const panel = await read('../src/OlgaRuntimePanel.tsx');

  assert.match(panel, /\/api\/run\/detect/);
  assert.match(panel, /\/api\/run\/olga-exe\/pick/);
  assert.match(panel, /\/api\/run\/olga-exe\/override/);
  assert.match(panel, /createNativeDialogRequestId/);
  assert.match(panel, /manual:settings/);
  for (const key of [
    'runtime.title', 'runtime.note', 'runtime.selected', 'runtime.reason',
    'runtime.none', 'runtime.selectedMark', 'runtime.pickExe',
    'runtime.clearOverride', 'runtime.refresh', 'runtime.offline',
    'runtime.pickFailed', 'runtime.clearFailed',
    'runtime.versionLabel', 'runtime.unknownVersion',
  ]) {
    assert.ok(key in ko, `ko misses ${key}`);
    assert.ok(key in en, `en misses ${key}`);
  }
});

test('settings mounts the runtime panel in the workspace section', async () => {
  const view = await read('../src/SettingsView.tsx');

  assert.match(view, /import OlgaRuntimePanel from '\.\/OlgaRuntimePanel'/);
  const workspace = view.slice(view.indexOf("section === 'workspace'"));
  assert.match(workspace, /<OlgaRuntimePanel \/>/);
});

test('run approval card warns on unverified runtime versions', async () => {
  const card = await read('../src/ApprovalCard.tsx');

  assert.match(card, /reviewed\.runtime_version/);
  assert.match(card, /startsWith\('2022\.1'\)/);
  assert.match(card, /t\('approval\.unverifiedVersion'\)/);
  assert.ok('approval.unverifiedVersion' in ko);
  assert.ok('approval.unverifiedVersion' in en);
  assert.notEqual(ko['approval.unverifiedVersion'], en['approval.unverifiedVersion']);
});
