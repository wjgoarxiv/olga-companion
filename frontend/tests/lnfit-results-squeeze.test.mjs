import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// lnfit HIGH: Results detail crush at 1280x800 with explorer+dock open.
// The rail (268px) + narrow centre (~500px) left the detail ~100px wide:
// "case.ppl" wrapped one letter per line and RUN/STATUS/MODIFIED chips clipped.
// Fix: a container query on the Results pane stacks list above detail (or gives
// the detail a min width) so no per-letter wrap and no clipped chip at
// 1024-1920 with both side panes open.
test('lnfit results: narrow Results pane stacks list above detail', async () => {
  const css = await read('../src/styles/results.css');
  // A container query (not viewport media) so it reacts to the width the
  // Results pane actually gets inside the workbench.
  assert.match(css, /@container[^{]*\{[\s\S]*?\.rv-view\s*\{[^}]*grid-template-columns:\s*1fr/s, 'a container query stacks .rv-view to one column when narrow');
});

test('lnfit results: detail head wraps and never breaks per letter', async () => {
  const css = await read('../src/styles/results.css');
  assert.match(css, /\.rv-head\s*\{[^}]*flex-wrap:\s*wrap/s, '.rv-head wraps instead of squeezing the file name');
});

test('lnfit results: lineage chips stay inside the detail column', async () => {
  const css = await read('../src/styles/results.css');
  // The detail column must not force a sideways cut: min-width 0 + no
  // sideways spill so chips wrap instead of clipping.
  assert.match(css, /\.rv-main\s*\{[^}]*min-width:\s*0/s, '.rv-main keeps min-width 0');
  assert.match(css, /\.result-lineage\s*\{[^}]*min-width:\s*0/s, '.result-lineage keeps min-width 0');
});
