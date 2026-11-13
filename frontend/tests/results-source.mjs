import { readFile } from 'node:fs/promises';

const RESULTS_SOURCE_FILES = [
  '../src/ResultsView.tsx',
  '../src/useResultExports.ts',
  '../src/ResultsLayout.tsx',
  '../src/ResultsPrompts.tsx',
  '../src/ResultsInventoryRail.tsx',
  '../src/ResultAnalysis.tsx',
  '../src/resultPresentation.ts',
  '../src/useResultSeriesOverlay.ts',
];

export async function readResultsSource(baseUrl) {
  const modules = await Promise.all(
    RESULTS_SOURCE_FILES.map((path) => readFile(new URL(path, baseUrl), 'utf8')),
  );
  return modules.join('\n');
}
