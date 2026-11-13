import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('findings panel starts empty-handed and names missing variables plainly', async () => {
  const panel = await read('../src/FindingsPanel.tsx');
  assert.match(panel, /판정/, 'the verdict action is labelled in Korean');
  assert.doesNotMatch(panel, /defaultValue\s*=\s*\{[^}]*[1-9]/, 'thresholds ship with no preset numbers');
  assert.match(panel, /필요해요/, 'missing data is a plain request, not an error dump');
  assert.match(panel, /HOL/, 'the message names the variable to add');
  assert.doesNotMatch(panel, /sweepExecute|approveSweep/, 'the panel never launches or approves anything');
});

test('findings report button is always available and sends those verdicts unchanged', async () => {
  const [panel, api, results] = await Promise.all([
    read('../src/FindingsPanel.tsx'),
    read('../src/resultApi.ts'),
    read('../src/useResultExports.ts'),
  ]);

  assert.match(panel, /setShownVerdicts\(response\.pending\.length > 0 \? response\.pending : response\.judgements\)/);
  assert.match(panel, /t\('findings\.makeReport'\)/, 'the report action is reachable with zero verdicts');
  assert.doesNotMatch(panel, /shownVerdicts\.length > 0/, 'no verdict gate on the report action');
  assert.match(panel, /verdicts:\s*shownVerdicts/);
  assert.match(panel, /figures:\s*sessionFigures\(\)/);
  assert.match(panel, /variables:\s*variableCodes/, 'the report names the loaded variables');
  assert.match(panel, /results_file:\s*selected\.id/);
  assert.match(panel, /저장을 취소했습니다/);
  assert.match(panel, /result\.basename/);
  assert.match(api, /\/api\/reports\/findings/);
  assert.match(panel, /saveArtifactAs\(/);
  assert.match(results, /rememberSessionFigures\(exported\.plots\)/);
  assert.doesNotMatch(panel, /shownVerdicts\.map\(/);
});
