import { readFile } from 'node:fs/promises';

const runSourcePaths = [
  '../src/useRunViewState.ts',
  '../src/useRunLifecycle.ts',
  '../src/useRunActions.ts',
  '../src/runViewModel.ts',
  '../src/RunViewOverview.tsx',
  '../src/RunSingleCasePanel.tsx',
  '../src/SweepParameterPicker.tsx',
  '../src/RunSweepPanel.tsx',
  '../src/RunView.tsx',
];

export async function readRunSource() {
  const sources = await Promise.all(
    runSourcePaths.map((path) => readFile(new URL(path, import.meta.url), 'utf8')),
  );
  return sources.join('\n');
}
