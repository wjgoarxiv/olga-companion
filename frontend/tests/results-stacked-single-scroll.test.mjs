import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// 2026-11-10, 1536x794 window with explorer, chat and the bottom dock open:
// the stacked Results pane gave the file list a fixed 260px row and left the
// detail a 162px row that scrolled on its own, so the chart sat below that
// small window, under the list. Stacked, the pane scrolls as one column.
function stackedBlock(css) {
  const start = css.indexOf('@container (max-width: 900px)');
  assert.notEqual(start, -1, 'the stacked container query exists');
  let depth = 0;
  for (let i = css.indexOf('{', start); i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}' && --depth === 0) return css.slice(start, i + 1);
  }
  throw new Error('unclosed container block');
}

test('stacked Results pane scrolls as one column, not list row plus detail row', async () => {
  const block = stackedBlock(await read('../src/styles/results.css'));
  assert.match(block, /\.rv-view\s*\{[^}]*overflow-y:\s*auto/, 'the pane itself scrolls');
  // 2026-11-11 round 1: an `auto` row let the list (a scroll box, min size 0)
  // collapse to 25px under the tall detail, clipping its heading. max-content
  // keeps the list at its own height, capped by its 260px max-height.
  assert.match(block, /\.rv-view\s*\{[^}]*grid-template-rows:\s*max-content auto/, 'the list row keeps its height');
  assert.match(block, /\.rv-main\s*\{[^}]*overflow-y:\s*visible/, 'the detail has no scroll window of its own');
  // .rv-view.empty (two classes) would otherwise keep the three-column grid and
  // drop the empty-state prompt into the hidden 8px resizer column.
  assert.match(block, /\.rv-view\.empty\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/, 'the empty pane stacks too');
  assert.match(block, /\.rv-main\s*\{[^}]*min-height:\s*auto/, 'the detail row takes its content height, not the leftover');
  // overflow-x: hidden would turn overflow-y: visible back into auto (CSS Overflow 3).
  assert.doesNotMatch(block, /\.rv-main\s*\{[^}]*overflow-x:\s*hidden/, 'sideways clipping uses clip, not hidden');
});
