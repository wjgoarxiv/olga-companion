import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { filterPaletteItems, moveRovingIndex } from '../src/ui/primitiveUtils.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('roving index wraps on arrows and jumps on Home/End', () => {
  assert.equal(moveRovingIndex(2, 4, 'ArrowRight'), 3);
  assert.equal(moveRovingIndex(3, 4, 'ArrowRight'), 0);
  assert.equal(moveRovingIndex(0, 4, 'ArrowLeft'), 3);
  assert.equal(moveRovingIndex(1, 4, 'Home'), 0);
  assert.equal(moveRovingIndex(1, 4, 'End'), 3);
  assert.equal(moveRovingIndex(0, 3, 'ArrowDown', 'vertical'), 1);
  assert.equal(moveRovingIndex(0, 3, 'ArrowRight', 'vertical'), 0);
  assert.equal(moveRovingIndex(1, 3, 'Enter'), 1);
});

test('palette filter matches labels and keywords case-insensitively', () => {
  const items = [
    { id: 'a', label: 'Preview run', keywords: 'F5' },
    { id: 'b', label: 'Toggle theme' },
  ];
  assert.deepEqual(filterPaletteItems(items, ''), items);
  assert.deepEqual(filterPaletteItems(items, 'preview').map((item) => item.id), ['a']);
  assert.deepEqual(filterPaletteItems(items, 'F5').map((item) => item.id), ['a']);
  assert.deepEqual(filterPaletteItems(items, 'TOGGLE').map((item) => item.id), ['b']);
  assert.deepEqual(filterPaletteItems(items, 'zzz'), []);
});

test('Tabs expose tablist semantics with arrow-key roving', async () => {
  const source = await read('../src/ui/Tabs.tsx');
  assert.match(source, /role="tablist"/);
  assert.match(source, /role="tab"/);
  assert.match(source, /role="tabpanel"/);
  assert.match(source, /aria-selected/);
  assert.match(source, /aria-controls/);
  assert.match(source, /moveRovingIndex\(index, items\.length, event\.key\)/);
  assert.match(source, /tabIndex=\{index === selected \? 0 : -1\}/);
});

test('Segmented is a radiogroup with arrow-key roving', async () => {
  const source = await read('../src/ui/Segmented.tsx');
  assert.match(source, /role="radiogroup"/);
  assert.match(source, /role="radio"/);
  assert.match(source, /aria-checked/);
  assert.match(source, /moveRovingIndex\(index, options\.length, event\.key\)/);
});

test('Menu exposes menu semantics with arrows, Home/End and Esc', async () => {
  const [source, utils] = await Promise.all([
    read('../src/ui/Menu.tsx'),
    read('../src/ui/primitiveUtils.ts'),
  ]);
  assert.match(source, /role="menu"/);
  assert.match(source, /role="menuitem"/);
  assert.match(source, /moveRovingIndex\(index, items\.length, event\.key, 'vertical'\)/);
  assert.match(utils, /ArrowUp/);
  assert.match(utils, /ArrowDown/);
  assert.match(utils, /key === 'Home'/);
  assert.match(utils, /key === 'End'/);
  assert.match(source, /Escape/);
});

test('CommandPalette wires combobox, listbox and active descendant', async () => {
  const source = await read('../src/ui/CommandPalette.tsx');
  assert.match(source, /role="combobox"/);
  assert.match(source, /role="listbox"/);
  assert.match(source, /role="option"/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /aria-activedescendant/);
  assert.match(source, /aria-autocomplete="list"/);
  assert.match(source, /ArrowDown/);
  assert.match(source, /aria-modal="true"/);
});

test('Field, Select, Table, IconButton, Toolbar, Panel, Badge, Kbd carry their contracts', async () => {
  const [field, select, table, icon, toolbar, panel, badge, kbd, popover] = await Promise.all([
    read('../src/ui/Field.tsx'),
    read('../src/ui/Select.tsx'),
    read('../src/ui/Table.tsx'),
    read('../src/ui/IconButton.tsx'),
    read('../src/ui/Toolbar.tsx'),
    read('../src/ui/Panel.tsx'),
    read('../src/ui/Badge.tsx'),
    read('../src/ui/Kbd.tsx'),
    read('../src/ui/Popover.tsx'),
  ]);
  assert.match(field, /htmlFor=\{controlId\}/);
  assert.match(field, /aria-describedby/);
  assert.match(field, /role="alert"/);
  assert.match(select, /<select/);
  assert.match(table, /<table/);
  assert.match(table, /scope="col"/);
  assert.match(table, /ui-num/);
  assert.match(icon, /aria-label=\{label\}/);
  assert.match(icon, /aria-hidden="true"/);
  assert.match(toolbar, /role="toolbar"/);
  assert.match(toolbar, /ui-toolbar-sep/);
  assert.match(panel, /<section/);
  assert.match(panel, /ui-panel-actions/);
  assert.match(badge, /ui-badge-/);
  assert.match(kbd, /<kbd/);
  assert.match(popover, /role="dialog"/);
  assert.match(popover, /Escape/);
});

test('Icon3D picks the theme render and stays silent when decorative', async () => {
  const source = await read('../src/ui/Icon3D.tsx');
  assert.match(source, /resolvedTheme/);
  assert.match(source, /`\/icons\/\$\{resolvedTheme\}\//);
  assert.match(source, /aria-hidden/);
  assert.match(source, /alt=\{alt \?\? ''\}/);
});

test('primitives stylesheet is bundled and existing ui keeps working', async () => {
  const [styles, button, status, receipt, skeleton, loader] = await Promise.all([
    read('../src/styles.css'),
    read('../src/ui/Button.tsx'),
    read('../src/ui/OperationStatus.tsx'),
    read('../src/ui/Receipt.tsx'),
    read('../src/ui/Skeleton.tsx'),
    read('../src/ui/ActivityLoader.tsx'),
  ]);
  assert.match(styles, /@import '\.\/styles\/primitives\.css';/);
  for (const [name, source] of [['Button', button], ['OperationStatus', status],
    ['Receipt', receipt], ['Skeleton', skeleton], ['ActivityLoader', loader]]) {
    assert.ok(source.length > 0, `${name} is intact`);
  }
  assert.match(button, /ui-button-/);
});
