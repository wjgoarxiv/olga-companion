import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('every position, branch and pipe input is a catalog select', async () => {
  const panel = await read('../src/FindingsPanel.tsx');
  const fields = await read('../src/FindingsCriterionFields.tsx');
  assert.doesNotMatch(panel, /placeholder="예: PIPELINE"/, 'no free-text branch example');
  assert.doesNotMatch(fields, /placeholder="예: PIPELINE"/, 'no free-text branch example');
  assert.doesNotMatch(panel + fields, /<input[^>]*placeholder="예: PIPE/, 'no free-text pipe example');
  assert.doesNotMatch(panel + fields, /placeholder="예: [0-9]/, 'no numeric example remains');
  assert.match(fields, /branchOptions|pipeOptions|positions/, 'options come from the opened file catalog');
  assert.match(fields, /<select/, 'positions, branches and pipes render as selects');
});

test('glossary wraps criterion names without touching the layout cap', async () => {
  const [fields, layout] = await Promise.all([
    read('../src/FindingsCriterionFields.tsx'),
    read('../src/ResultsLayout.tsx'),
  ]);
  assert.match(fields, /<GlossaryTerm/, 'criterion names and units carry glossary popovers');
  assert.match(layout, /import FindingsPanel from/, 'wiring stays a single import');
});

test('a report can be saved with zero verdicts and names the file', async () => {
  const panel = await read('../src/FindingsPanel.tsx');
  assert.doesNotMatch(panel, /shownVerdicts\.length > 0/, 'the report action is not gated on verdicts');
  assert.match(panel, /savedFile|저장됨/, 'the saved path is shown after saving');
});
