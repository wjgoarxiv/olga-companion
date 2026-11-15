import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

test('advanced sweep uses a guided recipe editor instead of two raw text fields', async () => {
  // Given: the advanced sweep panel and its visual contract.
  const panel = await read('../src/RunSweepPanel.tsx');
  const css = await readCss();

  // When: an operator configures a parameter study.
  assert.match(panel, /<SweepParameterPicker/);
  assert.match(panel, /<SweepValueBuilder/);
  assert.match(panel, /t\('run\.reviewCases', \{ count: sweepCaseCount \}\)/);

  // Then: the recipe remains legible, bounded, and accessible.
  assert.match(css, /\.sweep-recipe\s*\{[^}]*border-radius:\s*var\(--r-s\)/s);
  assert.doesNotMatch(css, /\.sweep-recipe\s*\{[^}]*border-left-color:/s);
  assert.match(css, /\.sweep-value-mode\s*\{[^}]*grid-template-columns:/s);
  assert.match(css, /\.sweep-value-chip\s*\{[^}]*white-space:\s*nowrap/s);
});

test('parameter picker discovers active-case keys without removing manual entry', async () => {
  // Given: a case-derived, read-only parameter catalog.
  const picker = await read('../src/SweepParameterPicker.tsx');
  const api = await read('../src/sweepApi.ts');

  // When: the active case changes or the catalog request cannot be completed.
  assert.match(picker, /useEffect/);
  assert.match(picker, /fetchSweepParameters\(base, controller\.signal\)/);
  assert.match(picker, /list="sweep-parameter-options"/);
  assert.match(picker, /Manual GENKEY path entry remains available/);

  // Then: the request stays on the authenticated transport and is abortable.
  assert.match(api, /apiFetch\('\/api\/sweep\/parameters'/);
  assert.match(api, /signal/);
});

test('range builder serializes readable OLGA values and enforces the case ceiling', async () => {
  // Given: the shared sweep value grammar.
  const { buildRangeSweepValues, splitSweepValues } = await import('../src/sweepValueGrammar.mjs');

  // When: an operator requests three evenly spaced values with an explicit unit.
  const values = buildRangeSweepValues({ start: 0, stop: 60, count: 3, unit: 's' });

  // Then: the existing backend grammar receives three readable values.
  assert.equal(values, '0 s,30 s,60 s');
  assert.deepEqual(splitSweepValues(values), ['0 s', '30 s', '60 s']);
  assert.equal(buildRangeSweepValues({ start: 0, stop: 60, count: 21, unit: 's' }), '');
});

test('range controls recover the current list when an operator switches modes', async () => {
  // Given: a curated list that was extended in list mode.
  const { readRangeSweepValues } = await import('../src/sweepValueGrammar.mjs');

  // When: the operator returns to the range editor.
  const range = readRangeSweepValues('3600 s,4800 s,6000 s,7200 s,8400 s', {
    start: 0,
    stop: 0,
    count: 2,
    unit: '',
  });

  // Then: every visible range control reflects the live five-value recipe.
  assert.deepEqual(range, { start: 3600, stop: 8400, count: 5, unit: 's' });
});
