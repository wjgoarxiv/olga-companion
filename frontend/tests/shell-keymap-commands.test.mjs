import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { SHELL_COMMANDS } from '../src/shell/commands.ts';
import { matchShellShortcut } from '../src/shell/keymap.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const key = (keyName, ctrl = true) => ({ key: keyName, ctrlKey: ctrl, metaKey: false });

test('every documented binding dispatches its shell action', async () => {
  assert.equal(matchShellShortcut(key('1')), 'go-case');
  assert.equal(matchShellShortcut(key('2')), 'go-results');
  assert.equal(matchShellShortcut(key('3')), 'go-runs');
  assert.equal(matchShellShortcut(key('4')), 'go-settings');
  assert.equal(matchShellShortcut(key('j')), 'toggle-dock');
  assert.equal(matchShellShortcut(key('J')), 'toggle-dock');
  assert.equal(matchShellShortcut({ key: '`', ctrlKey: true, metaKey: false }), 'toggle-panel');
  assert.equal(matchShellShortcut(key('F5', false)), 'preview-run');
  assert.equal(matchShellShortcut(key('?', false)), 'show-shortcuts');
  assert.equal(matchShellShortcut(key('k')), 'open-palette');
  assert.equal(matchShellShortcut(key('K')), 'open-palette');
  assert.equal(matchShellShortcut(key('x')), null);
  assert.equal(matchShellShortcut(key('Escape', false)), null);
});

test('the palette opens from the keyboard even while typing', async () => {
  assert.equal(matchShellShortcut(key('k')), 'open-palette');
});

test('the command registry covers every dispatched action with a dictionary label', async () => {
  const ids = new Set(SHELL_COMMANDS.map((command) => command.id));
  for (const id of ['go-case', 'go-results', 'go-runs', 'go-settings', 'toggle-dock', 'toggle-panel', 'validate', 'preview-run', 'open-run', 'open-palette', 'toggle-theme', 'switch-language', 'show-shortcuts']) {
    assert.ok(ids.has(id), `palette registry covers ${id}`);
  }
  const [ko, en] = await Promise.all([read('../src/i18n/ko.ts'), read('../src/i18n/en.ts')]);
  for (const command of SHELL_COMMANDS) {
    assert.ok(ko.includes(`'${command.labelKey}':`), `${command.id} has a ko label`);
    assert.ok(en.includes(`'${command.labelKey}':`), `${command.id} has an en twin`);
  }
});

test('Run shortcut and Run commands open the preview only, never execute', async () => {
  const [dispatch, titlebar, commands] = await Promise.all([
    read('../src/shell/useWorkbenchCommands.ts'),
    read('../src/shell/TitleBar.tsx'),
    read('../src/shell/commands.ts'),
  ]);
  assert.match(dispatch, /else if \(id === 'preview-run' \|\| id === 'open-run'\) selectView\('run'\)/);
  for (const [name, source] of [['dispatch', dispatch], ['title bar', titlebar], ['registry', commands]]) {
    assert.doesNotMatch(source, /executeApproval|runExecute|sweepExecute|session\.execute/, `${name} never executes a run`);
  }
});

test('layout state round-trips through storage with defaults on throwing storage', async () => {
  const layout = await read('../src/shell/useWorkbenchLayout.ts');
  assert.match(layout, /WORKBENCH_LAYOUT_KEY = 'olga-companion\.workbench-layout\.v1'/);
  assert.match(layout, /readLocalStorage\(LEGACY_VIEW_KEY\)/, 'legacy olga_view key is carried over');
  assert.match(layout, /if \(!\(error instanceof SyntaxError\)\) throw error;\s*return DEFAULT_LAYOUT;/s, 'corrupt JSON falls back to defaults');
  const storage = await read('../src/safeLocalStorage.ts');
  assert.match(storage, /catch[\s\S]*?return null/s, 'throwing storage reads as empty so defaults apply');
  assert.match(layout, /writeLocalStorage\(WORKBENCH_LAYOUT_KEY/, 'layout persists under its own key');
});
