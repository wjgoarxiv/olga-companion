import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('runtime candidates are stable identities carried through preview and execution', async () => {
  const api = await readSessionSource(import.meta.url);
  const run = await readRunSource();

  assert.match(api, /interface OlgaCandidate[\s\S]*candidate_id:[\s\S]*runtime_id:/);
  assert.match(api, /interface OlgaDetection[\s\S]*candidate_id:[\s\S]*runtime_id:/);
  assert.match(api, /runPreview\(source: string, candidateId: string/);
  assert.match(api, /JSON\.stringify\(\{ source, timeout_s: timeoutS, candidate_id: candidateId \}\)/);
  assert.match(api, /runExecute\(source: string, candidateId: string, selectionId: string/);
  assert.match(api, /candidate_id: candidateId, selection_id: selectionId/);
  assert.match(run, /t\('run\.runtimeField'\)/);
  assert.match(run, /setSelectedCandidateId\(event\.target\.value\)[\s\S]*setPreview\(null\)[\s\S]*setStatus\(null\)/);
  assert.match(run, /session\.runPreview\(active\.path, selectedCandidateId, timeoutHours \* 3600\)/);
  assert.match(run, /session\.runExecute\(active\.path, preview\.candidate_id, preview\.selection_id, preview\.timeout_s\)/);
  assert.doesNotMatch(run, /<option[^>]*>[^<]*\.exe/, 'runtime option labels must never contain executable paths');
});

test('the run time limit is chosen in hours, re-previews on change, and shows on the receipt', async () => {
  const run = await readRunSource();

  assert.match(run, /useState\(1\)[\s\S]*timeoutHours/, 'the limit starts at one hour');
  assert.match(run, /aria-label=\{t\('run\.timeLimitField'\)\}/);
  assert.match(run, /min=\{1\}[\s\S]*max=\{RUN_LIMIT_MAX_HOURS\}/);
  assert.match(run, /RUN_LIMIT_MAX_HOURS = 168/, 'seven days, the same ceiling as the sidecar');
  assert.match(run, /setTimeoutHours\([\s\S]*\);\s*setPreview\(null\)/, 'a changed limit needs a fresh preview, since the approval is bound to it');
  assert.match(run, /t\('run\.timeLimit'\)[\s\S]*preview\.timeout_s/);
});

test('preview makes validation and source isolation explicit and fails closed', async () => {
  const run = await readRunSource();

  assert.match(run, /t\('run\.validator'\)/);
  assert.match(run, /preview\.validation\.valid \? t\('run\.pass'\) : t\('run\.fail'\)/);
  assert.match(run, /t\('run\.sandbox'\)/);
  assert.match(run, /t\('run\.ownerSource'\)/);
  assert.match(run, /t\('run\.ownerDetail'\)/);
  assert.match(run, /t\('approval\.approveRun'\)/);
  assert.match(run, /disabled=\{blockedReason !== ''\}/);
  assert.match(run, /approveBlockedReason\(\{ operationActive: safetyOperationActive, runReady, preview, usedSelectionId/);
  const gate = await readFile(new URL('../src/runPresentation.mjs', import.meta.url), 'utf8');
  assert.match(gate, /operationActive[\s\S]*!runReady[\s\S]*!preview\?\.selection_id[\s\S]*!preview\.validation\?\.valid/, 'every original disabling condition still blocks approval, in order');
  assert.doesNotMatch(run, /basename\(preview\.cwd_template\)/, 'sandbox should be described as an isolated destination, not a misleading path fragment');
});

test('run history restores durable status and outputs can open exact TPL results', async () => {
  const api = await readSessionSource(import.meta.url);
  const run = await readRunSource();
  const panel = await read('../src/RunFailurePanel.tsx');

  assert.match(api, /fetchRunHistory\(source: string, limit = 20\)/);
  assert.match(api, /new URLSearchParams\(\{ source, limit: String\(limit\) \}\)/);
  assert.match(run, /session\.fetchRunHistory\(/);
  assert.match(run, /catch \(cause\) \{[\s\S]*OLGA detection failed[\s\S]*const history = await session\.fetchRunHistory\(/, 'history restoration is independent of current runtime detection');
  assert.match(run, /restored && runStatusIsPollable\(restored\)/);
  assert.match(run, /startRunPolling\(restored\.run_id\)/);
  assert.match(api, /interface RunOutput[\s\S]*sha256:[\s\S]*result_id\?:/);
  assert.match(panel, /status\.run_id/);
  assert.match(panel, /status\.outputs\.map/);
  assert.match(panel, /t\('run\.openTpl'\)/);
  assert.match(panel, /onOpenResult\?\.\(output\.result_id\)/);
  assert.match(panel, /recovery_unknown/);
  assert.doesNotMatch(panel, /output\.path/, 'absolute output paths are not rendered');
});

test('run history is scoped to the active source and receipts identify that source', async () => {
  const api = await readSessionSource(import.meta.url);
  const run = await readRunSource();
  const panel = await read('../src/RunFailurePanel.tsx');

  assert.match(api, /fetchRunHistory\(source: string, limit = 20\)/);
  assert.match(api, /new URLSearchParams\(\{ source, limit: String\(limit\) \}\)/);
  assert.match(run, /session\.fetchRunHistory\(activeCase\.path, 20\)/);
  assert.doesNotMatch(run, /session\.fetchRunHistory\(20\)/, 'global history must never be attributed to the active case');
  assert.match(api, /readonly source_name\?: string/);
  assert.match(panel, /t\('run\.sourceCase'\)/);
  assert.match(panel, /basename\(status\.source_name/);
});

test('preview renders only the path-free display command including WSL launches', async () => {
  const api = await readSessionSource(import.meta.url);
  const run = await readRunSource();

  assert.match(api, /readonly display_command: readonly string\[\]/);
  assert.match(run, /preview\.display_command\.map/);
  assert.doesNotMatch(run, /preview\.command/, 'exact argv must never reach the operator preview');
  assert.doesNotMatch(run, /basename\(String\(part\)\)/, 'basename-only first-argv masking leaks the duplicate WSL executable path');
});

test('approval enters starting before the first status and stop waits for running', async () => {
  const run = await readRunSource();

  assert.match(run, /const \[starting, setStarting\] = useState\(false\)/);
  assert.match(run, /setStarting\(true\)[\s\S]*await session\.runExecute/);
  assert.match(run, /setStarting\(false\)[\s\S]*setStatus\(next\)/);
  assert.match(run, /starting \? 'starting' : liveStatus\?\.state \|\| 'ready'/);
  assert.match(run, /const runPollable = status != null && runStatusIsPollable\(status\)/);
  assert.match(run, /const runCancellable = runPollable && status\?\.state !== 'finalizing'/);
  assert.match(run, /\{runCancellable && <Button[\s\S]*status\?\.cancel_requested \? t\('run\.cancelRequested'\) : t\('run\.stopRun'\)/);
});

test('native failure actions become numbered operator steps without retry', async () => {
  const panel = await read('../src/RunFailurePanel.tsx');

  assert.match(panel, /function actionSteps\(action: string\): string\[\]/);
  assert.match(panel, /<ol className="run-failure-steps" aria-label="Operator recovery steps">/);
  assert.match(panel, /actionSteps\(failure\.action\)\.map/);
  assert.match(panel, /t\('run\.autoRetryOff'\)/);
});
