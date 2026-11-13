import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function pureLines(source) {
  return source
    .split('\n')
    .filter((line) => line.trim() && !line.trim().startsWith('//')).length;
}

test('ResultsView stays a bounded orchestrator after its presentation is extracted', async () => {
  // Given: the Results route entrypoint.
  const results = await read('../src/ResultsView.tsx');

  // When: its orchestration boundary is inspected.
  const codeLines = pureLines(results);

  // Then: rendering and display helpers live behind explicit result modules.
  assert.ok(codeLines <= 250, `ResultsView.tsx should stay <=250 pure LOC, got ${codeLines}`);
  assert.match(results, /import ResultsLayout from '\.\/ResultsLayout'/);
  assert.match(results, /from '\.\/resultPresentation'/);
  assert.match(results, /<ResultsLayout\b/);
  assert.doesNotMatch(results, /<aside\b|<section\b/, 'the route orchestrator does not own result DOM regions');
});

test('result tab modules stay reviewable and the layout delegates to them', async () => {
  // Given: the todo-9 Plot/Table/Verdict split and the inventory rail.
  const [layout, plot, picker, table, chart, panel, fields] = await Promise.all([
    read('../src/ResultsLayout.tsx'),
    read('../src/ResultPlotTab.tsx'),
    read('../src/VariablePicker.tsx'),
    read('../src/SeriesTable.tsx'),
    read('../src/TrendChart.tsx'),
    read('../src/FindingsPanel.tsx'),
    read('../src/FindingsCriterionFields.tsx'),
  ]);

  // When: each tab module is measured.
  // Then: every module keeps a reviewable ceiling for its own surface.
  for (const [name, source, ceiling] of [
    ['ResultPlotTab.tsx', plot, 160],
    ['VariablePicker.tsx', picker, 130],
    ['SeriesTable.tsx', table, 120],
    ['TrendChart.tsx', chart, 220],
    ['FindingsCriterionFields.tsx', fields, 160],
  ]) {
    assert.ok(pureLines(source) <= ceiling, `${name} should stay <=${ceiling} pure LOC`);
  }

  // And the layout delegates instead of owning every region.
  for (const [needle, meaning] of [
    [/<ResultsInventoryRail\b/, 'inventory rail'],
    [/<ResultPlotTab\b/, 'plot tab'],
    [/<SeriesTable\b/, 'table tab'],
    [/<FindingsPanel\b/, 'verdict tab'],
  ]) {
    assert.match(layout, needle, `ResultsLayout delegates the ${meaning}`);
  }
  assert.doesNotMatch(plot, /<aside\b/, 'the plot tab does not own aside regions');
});
