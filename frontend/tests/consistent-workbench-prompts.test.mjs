import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('operational blank states share the approved workbench prompt language', async () => {
  // Given: the three primary operational surfaces and the stylesheet entrypoint.
  const [workspace, run, resultsLayout, resultsPrompts, styles] = await Promise.all([
    read('../src/WorkspaceView.tsx'),
    read('../src/RunViewOverview.tsx'),
    read('../src/ResultsLayout.tsx'),
    read('../src/ResultsPrompts.tsx'),
    read('../src/styles.css'),
  ]);

  // When: their no-selection and no-inventory presentations are inspected.
  // Then: each delegates to one shared, context-led prompt instead of bespoke cards.
  for (const source of [workspace, run, resultsPrompts]) {
    assert.match(source, /WorkbenchPrompt/);
  }
  assert.match(resultsLayout, /Results(?:Loading|Selection)Prompt|EmptyResultsPrompt/);
  assert.match(styles, /workbench-prompts\.css/);
  assert.doesNotMatch(workspace, /<p className="ws-empty">Pick a case/);
  assert.doesNotMatch(`${resultsLayout}\n${resultsPrompts}`, /className="rv-selection-prompt"/);
});

test('shared prompts keep one hierarchy: orientation, action, and live context', async () => {
  // Given: the stylesheet entrypoint and the shared prompt contract.
  const [styles, workspace, run, results] = await Promise.all([
    read('../src/styles.css'),
    read('../src/WorkspaceView.tsx'),
    read('../src/RunViewOverview.tsx'),
    read('../src/ResultsPrompts.tsx'),
  ]);

  // When: the approved design grammar is reflected into sibling states.
  // Then: the common surface and its accessible context label are explicit.
  assert.match(styles, /workbench-prompts\.css/);
  for (const source of [workspace, run, results]) {
    assert.match(source, /contextLabel=/);
    assert.match(source, /contextValue=/);
  }
});
