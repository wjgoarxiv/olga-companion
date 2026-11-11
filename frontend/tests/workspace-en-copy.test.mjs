import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { translate } from '../src/i18n/index.ts';

const HANGUL = /[가-힣]/;

// Prompt strings resolve through t() first (ko is only a missing-key
// fallback), so every referenced key needs both twins and Hangul-free en.
function workspaceKeys(view) {
  const keys = new Set();
  for (const match of view.matchAll(/t\('workspace\.([A-Za-z]+)'\)/g)) {
    keys.add(`workspace.${match[1]}`);
  }
  for (const match of view.matchAll(/pickCountKey\('workspace\.([A-Za-z]+)'/g)) {
    keys.add(`workspace.${match[1]}_one`);
    keys.add(`workspace.${match[1]}_other`);
  }
  return [...keys].sort();
}

test('workspace empty/list states render no Hangul in English mode', async () => {
  const view = await readFile(new URL('../src/WorkspaceView.tsx', import.meta.url), 'utf8');
  const keys = workspaceKeys(view);
  assert.ok(keys.length > 20, `the view routes its chrome through the dictionary (found ${keys.length})`);
  for (const key of keys) {
    const rendered = translate('en', key);
    assert.ok(rendered.length > 0, `${key} has an English twin`);
    assert.doesNotMatch(rendered, HANGUL, `${key} renders Hangul-free in English mode`);
    assert.ok(translate('ko', key).length > 0, `${key} has a ko value`);
  }
});
