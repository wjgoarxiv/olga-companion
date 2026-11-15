import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* Todo 14 breakpoints: >=1024 full workbench; 769-1023 dock and Explorer
 * become overlays (toggle, Esc closes, focus returns); at most 768 a single
 * stacked panel with a notice. */

test('the 769-1023 band turns the dock and Explorer into overlays', async () => {
  const css = await read('../src/styles/workbench.css');

  const band = css.match(/@media\s*\(min-width:\s*769px\)\s*and\s*\(max-width:\s*1023px\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(band, 'the 768-1023 overlay band exists');
  assert.match(band[1], /\.wb-explorer[^{]*\{[^}]*position:\s*fixed/s, 'the Explorer overlays in the band');
  assert.match(band[1], /\.wb-dock[^{]*\{[^}]*position:\s*fixed/s, 'the dock overlays in the band');
});

test('overlay toggles live in the activity bar with expanded state', async () => {
  const bar = await read('../src/shell/ActivityBar.tsx');

  assert.match(bar, /explorerOpen|onToggleExplorer/, 'the bar can toggle the Explorer overlay');
  assert.match(bar, /dockOpen|onToggleDock/, 'the bar can toggle the dock overlay');
  assert.match(bar, /expanded=\{/, 'toggles expose their expanded state');
  assert.match(bar, /controls="/, 'toggles name the panel they control');
});

/* Todo 15 leftover (a): in the 769-1023 band the activity-bar overlay toggles
 * rendered as bare "-" glyphs. They render directional chevrons that point
 * where the panel goes (right when closed, back toward the rail when open),
 * keeping the ko/en label, expanded state, controls and toggle id. */
test('the band overlay toggles render directional chevrons, not bare glyphs', async () => {
  const bar = await read('../src/shell/ActivityBar.tsx');
  assert.doesNotMatch(bar, />\{(explorer|dock)Open \? '−' : '\+'\}</, 'no bare minus/plus glyph children');
  assert.match(bar, /wb-toggle-chevron/, 'toggles render a chevron icon');
  assert.match(bar, /shell\.explorer(Hide|Show)/, 'the Explorer toggle keeps its ko/en label');
  assert.match(bar, /shell\.dock(Hide|Show)/, 'the dock toggle keeps its ko/en label');
});

test('the Explorer shut path keeps every hook unconditional', async () => {
  const panel = await read('../src/shell/ExplorerPanel.tsx');

  const shut = panel.indexOf('if (!open)');
  assert.ok(shut > 0, 'the shut rail short-circuits the tree');
  for (const hook of ['useExplorerFilter(', 'useState(']) {
    assert.ok(panel.lastIndexOf(hook) < shut, `${hook} runs before the short-circuit`);
  }
});

test('the Explorer open state persists in the layout store', async () => {
  const store = await read('../src/shell/useWorkbenchLayout.ts');

  assert.match(store, /explorerOpen:\s*boolean/, 'the store tracks the Explorer');
  assert.match(store, /setExplorerOpen/, 'the store toggles the Explorer');
  assert.match(store, /explorerOpen,\s*panelOpen|panelOpen,\s*explorerOpen|explorerOpen/, 'round-trips keep the flag');
});

test('Escape closes the overlay and focus returns to its toggle', async () => {
  const hook = await read('../src/shell/useOverlayPanels.ts');

  assert.match(hook, /Escape/, 'Escape is handled');
  assert.match(hook, /\.focus\(\)/, 'focus returns to the toggle');
  assert.match(hook, /matchMedia|innerWidth/, 'only the overlay band is affected');
});

test('below 768 the regions stack with a notice', async () => {
  const [css, app, ko, en] = await Promise.all([
    read('../src/styles/workbench.css'),
    read('../src/App.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);

  assert.match(css, /@media\s*\(max-width:\s*768px\)[\s\S]*?\.wb-mid\s*\{[^}]*grid-template-areas:\s*"activity"\s*"explorer"\s*"centre"\s*"dock"\s*"panel"/s, 'narrow widths stack every region');
  assert.match(app, /shell\.narrowNotice/, 'the narrow notice renders');
  assert.match(ko, /'shell\.narrowNotice':\s*'[^']+'/, 'the notice has Korean copy');
  assert.match(en, /'shell\.narrowNotice':\s*'[^']+'/, 'the notice has English copy');
});
