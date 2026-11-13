import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const runModules = [
  'RunView.tsx',
  'useRunViewState.ts',
  'useRunLifecycle.ts',
  'useRunActions.ts',
  'runViewModel.ts',
  'RunViewOverview.tsx',
  'RunSingleCasePanel.tsx',
  'RunSweepPanel.tsx',
];

test('Run cockpit modules stay reviewable after cohesive extraction', async () => {
  // Given: every source module that composes the public Run cockpit.
  const sources = await Promise.all(runModules.map(async (fileName) => ({
    fileName,
    source: await readFile(new URL(`../src/${fileName}`, import.meta.url), 'utf8'),
  })));

  // When: blank lines and line-only comments are excluded from the review budget.
  const lineCounts = sources.map(({ fileName, source }) => ({
    fileName,
    pureLines: source
      .split('\n')
      .filter((line) => line.trim() !== '' && !line.trimStart().startsWith('//'))
      .length,
  }));

  // Then: each responsibility remains within the project review ceiling.
  for (const { fileName, pureLines } of lineCounts) {
    assert.ok(pureLines <= 250, `${fileName} has ${pureLines} pure lines; expected at most 250`);
  }
});
