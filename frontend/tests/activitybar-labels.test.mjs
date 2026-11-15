import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function pxOf(css, selector, prop) {
  const rule = new RegExp(`${selector}\\s*\\{[^}]*?${prop}:\\s*(\\d+)px`, 's').exec(css);
  return rule ? Number(rule[1]) : null;
}

/* W3-L2 (M7): the activity rail names its views. Visible text at >=1280px
   viewport (chrome, not pane); below that icons keep tooltips + aria-labels.
   Targets stay 44px; buttons expose their Ctrl+1..4 shortcuts. */

test('view buttons render visible labels from the nav dictionary', async () => {
  const bar = await read('../src/shell/ActivityBar.tsx');
  for (const view of ['workspace', 'results', 'run', 'settings']) {
    assert.match(bar, new RegExp(`nav\\.${view}`), `${view} label reuses the nav key`);
  }
  assert.match(bar, /visibleLabel=\{/, 'labels pass through the button as visible text');
});

test('overlay toggles label themselves with the existing shell keys', async () => {
  const bar = await read('../src/shell/ActivityBar.tsx');
  assert.match(bar, /shell\.explorer(Hide|Show)/, 'explorer toggle reuses shell keys');
  assert.match(bar, /shell\.dock(Hide|Show)/, 'dock toggle reuses shell keys');
});

test('rail buttons expose their keyboard shortcuts', async () => {
  const bar = await read('../src/shell/ActivityBar.tsx');
  for (const n of [1, 2, 3, 4]) {
    assert.match(bar, new RegExp(`Control\\+${n}`), `Ctrl+${n} shortcut surfaced`);
  }
  assert.match(bar, /aria-keyshortcuts|keyshortcuts/, 'shortcut lands on the button accessibly');
});

test('labels show at >=1280 and hide below (tooltips persist)', async () => {
  const css = await read('../src/styles/workbench.css');
  assert.match(css, /@media\s*\(\s*min-width:\s*1280px\s*\)[\s\S]{0,1200}?\.wb-activity \.ui-iconbutton-label\s*\{[^}]*?display:\s*(block|inline|flex|inline-block)/, 'labels visible at >=1280');
  assert.match(css, /\.wb-activity \.ui-iconbutton-label\s*\{[^}]*?display:\s*none/, 'labels hidden below 1280');
  const bar = await read('../src/shell/ActivityBar.tsx');
  assert.match(bar, /title=\{/, 'tooltips persist for the icon-only widths');
});

test('rail targets keep 44px hit areas', async () => {
  const css = await read('../src/styles/workbench.css');
  assert.equal(pxOf(css, '\\.wb-activity \\.ui-iconbutton', 'width'), 44, 'rail buttons stay 44px wide');
  assert.ok((pxOf(css, '\\.wb-activity \\.ui-iconbutton', 'min-height') ?? 0) >= 44, 'rail buttons keep >=44px height with labels');
});
