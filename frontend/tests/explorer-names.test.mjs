import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';
import { splitNameHalves } from '../src/fileNameDisplay.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// Names follow-up: long same-prefix names must stay distinguishable.

// 1. Inside a homogeneous type group the repeated suffix column goes away;
//    mixed groups keep it. The tooltip and the accessible name keep the full
//    name (extension included) in every group.
test('explorer drops the repeated suffix inside homogeneous type groups', async () => {
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.match(panel, /group !== 'cases' && group !== 'pvt'|showSuffix/, 'cases and PVT groups hide the repeated suffix');
  assert.match(panel, /title=\{item\.name\}/, 'the tooltip keeps the full name with its extension');
  assert.match(panel, /aria-label=\{`\$\{item\.name\}/, 'the accessible name keeps the extension');
  assert.match(panel, /wb-explorer-ext/, 'mixed groups still pin the suffix');
});

// 2. The tree is resizable through the shared handle: persisted, clamped,
//    keyboard-operable, ~280 px at >=1440 px and 248 px below.
test('explorer width resizes through the shared handle with a safe default', async () => {
  const [panel, wb, resizable] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/styles/workbench.css'),
    read('../src/styles/resizable-panels.css'),
  ]);
  assert.match(panel, /PanelResizeHandle/, 'the tree uses the shared resize primitive');
  assert.match(panel, /EXPLORER_WIDTH_KEY = 'olga-companion\.explorer\.width'/, 'the width persists');
  assert.match(panel, /storageKey=\{EXPLORER_WIDTH_KEY\}/, 'the handle writes that key');
  assert.match(panel, /EXPLORER_MIN_WIDTH = 200/, 'the width clamps at 200');
  assert.match(panel, /EXPLORER_MAX_WIDTH = 480/, 'the width clamps at 480');
  assert.match(panel, /innerWidth >= 1440 \? 280 : 248/, 'fresh default is ~280 at >=1440 and 248 below');
  assert.match(panel, /t\('explorer\.resize'\)/, 'the separator label reads the dictionary');
  assert.equal(ko['explorer.resize'], '탐색기 너비 조절');
  assert.equal(en['explorer.resize'], 'Resize Explorer');
  assert.match(wb, /\.wb-explorer-resizer\s*\{[^}]*grid-area:\s*exhandle/s, 'the handle owns a grid track beside the tree');
  assert.match(resizable, /\.wb-explorer/, 'narrow viewports reset the tree width');
});

// 3. Overflow truncates in the middle: the distinguishing tail stays visible,
//    and nothing truncates while the full name fits.
test('long names middle-truncate with the tail pinned', async () => {
  const [panel, css] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/styles/workbench.css'),
  ]);
  assert.match(panel, /splitNameHalves/, 'the tree renders two halves');
  assert.match(panel, /wb-explorer-name-head/, 'the head half exists');
  assert.match(panel, /wb-explorer-name-tail/, 'the tail half exists');
  assert.match(
    css,
    /\.wb-explorer-name-head\s*\{[^}]*overflow:\s*hidden[^}]*text-overflow:\s*ellipsis/s,
    'the head ellipsizes on real overflow',
  );
  assert.match(
    css,
    /\.wb-explorer-name-tail\s*\{[^}]*flex:\s*0\s*0\s*auto/s,
    'the tail never shrinks away',
  );
});

test('the head never stretches away from the tail', async () => {
  const css = await read('../src/styles/workbench.css');
  assert.match(
    css,
    /\.wb-explorer-name-head\s*\{[^}]*flex:\s*0\s*1\s*auto/s,
    'the head shrink-wraps its text so the tail sits right after the ellipsis',
  );
});

test('the empty tree names the active shared filter', async () => {
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.match(panel, /noMatchFor/, 'the empty message carries the needle key');
  assert.match(panel, /noMatchFor', \{ needle: filter \}/, 'the active shared filter text is shown');
  assert.equal(ko['explorer.noMatchFor'].includes('{needle}'), true, 'ko names the filter');
  assert.equal(en['explorer.noMatchFor'].includes('{needle}'), true, 'en names the filter');
});

test('splitNameHalves keeps short names whole and pins the tail', () => {
  assert.deepEqual(splitNameHalves('diag_b2_dt'), { head: 'diag_b2_dt', tail: '' });
  const long = 'spacing_demo_alpha_flowpath_pipeline_line';
  const parts = splitNameHalves(long);
  assert.equal(parts.head + parts.tail, long, 'the halves rejoin to the full name');
  assert.equal(parts.tail, long.slice(-5), 'the tail keeps the distinguishing end');
  assert.ok(parts.head.length > 8, 'the head keeps orientation context');
});
