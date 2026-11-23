import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('glossary popover cites its source and stays silent for unknown terms', async () => {
  const { findEntry } = await import('../src/glossary.ts');
  const entries = [
    { term: 'PT', kind: 'output_variable', meaning: '압력', source: { file: 'resultPresentation.ts', line: 10 } },
  ];
  const known = findEntry(entries, 'pt');
  assert.ok(known, 'lookup is case-insensitive');
  assert.equal(known.meaning, '압력');
  assert.equal(findEntry(entries, 'NO_SUCH_TERM'), null, 'unknown terms resolve to nothing, never invented text');
  assert.equal(findEntry(entries, ''), null);
});

test('one shared glossary trigger is keyboard and touch reachable', async () => {
  // Plotted chips live in the plot tab since the todo-9 surface split.
  const [component, css, plotTab, checklist] = await Promise.all([
    read('../src/GlossaryTerm.tsx'),
    read('../src/styles/controls.css'),
    read('../src/ResultPlotTab.tsx'),
    read('../src/NewCaseChecklist.tsx'),
  ]);
  assert.match(component, /출처:/, 'the popover cites file:line');
  assert.match(component, /tabIndex=\{0\}/, 'the trigger is focusable');
  assert.match(component, /Escape/, 'Esc closes the popover');
  assert.match(component, /aria-expanded/, 'the open state is exposed');
  assert.match(css, /\(pointer:\s*coarse\)[\s\S]*?\.glossary-term[^{]*\{[^}]*min-height:\s*44px/s, 'touch targets reach 44px on coarse pointers');
  assert.match(plotTab, /<GlossaryTerm/, 'results variable chips explain their terms');
  assert.match(checklist, /<GlossaryTerm/, 'checklist output values explain their terms');
});
