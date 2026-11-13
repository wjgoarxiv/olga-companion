import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('recovery_unknown renders an honest status without a run receipt claim', async () => {
  const panel = await read('../src/RunFailurePanel.tsx');

  assert.match(panel, /const hasRunEvidence = TERMINAL_RUN_STATES\.has\(status\.state\)/);
  assert.match(panel, /\{hasRunEvidence && \([\s\S]*<Receipt title=\{t\('run\.receipt'\)\}/);
  assert.match(panel, /status\.state === 'recovery_unknown'[\s\S]*<OperationStatus[\s\S]*title=\{t\('run\.recoveryUnknown'\)\}/);
});

test('run context and poll failures expose one full-context retry outside the active-case branch', async () => {
  const run = await readRunSource();

  assert.match(run, /const \[contextGeneration, setContextGeneration\] = useState\(0\)/);
  assert.match(run, /useEffect\(\(\) => \{[\s\S]*session\.fetchActiveCase\(\)[\s\S]*session\.runDetect\(activeCase\.path\)[\s\S]*session\.fetchRunHistory\(activeCase\.path, 20\)[\s\S]*\}, \[contextGeneration\]\)/);
  assert.match(run, /function retryRunContext\(\)[\s\S]*stopPolling\(\)[\s\S]*setContextGeneration\(\(generation\) => generation \+ 1\)/);
  assert.match(run, /t\('run\.retryContext'\)/);
  assert.match(run, /busyLabel=\{t\('run\.retryBusy'\)\}/);
  const errorStatus = run.indexOf('{error && <OperationStatus');
  const activeBranch = run.indexOf('{!contextUnavailable && active?.path && (');
  assert.ok(errorStatus >= 0 && activeBranch > errorStatus, 'context failure is visible even when no active path loaded');
});

test('failed active-case loading is unavailable context, never a confirmed empty workspace', async () => {
  const run = await readRunSource();

  assert.match(run, /const \[contextUnavailable, setContextUnavailable\] = useState\(false\)/);
  assert.match(run, /const activeCase = await session\.fetchActiveCase\(\);[\s\S]*setContextUnavailable\(false\)/);
  assert.match(run, /Active case loading failed:[\s\S]*setContextUnavailable\(true\)/);
  assert.match(run, /text\('run\.titleMissing'\)/);
  assert.match(run, /text\('run\.engineRetry'\)/);
  assert.match(run, /contextUnavailable\s*\? t\('run\.titleMissing'\)/);
  assert.match(run, /\{activeLoaded && !contextUnavailable && !active\?\.path && \(/);
  assert.doesNotMatch(run, /\{activeLoaded && !active\?\.path && \(/);
  assert.match(run, /\{!contextUnavailable && active\?\.path && \(/);
  assert.doesNotMatch(run, /\{active\?\.path && \(/);
});

test('all six run and sweep operations reject stale continuations and execution cannot poll after unmount', async () => {
  const run = await readRunSource();

  assert.match(run, /mountedRef = useRef\(false\)/);
  assert.match(run, /operationRequestRef = useRef\(createRequestEpoch\(\)\)/);
  assert.match(run, /mountedRef\.current = true;[\s\S]*mountedRef\.current = false;[\s\S]*operationRequestRef\.current\.invalidate\(\)[\s\S]*stopPolling\(\)/);
  assert.match(run, /function operationIsCurrent\(requestId: number\)[\s\S]*mountedRef\.current && operationRequestRef\.current\.isCurrent\(requestId\)/);
  assert.equal((run.match(/operationRequestRef\.current\.begin\(\)/g) || []).length, 6, 'every run/sweep request begins a shared operation epoch');

  for (const operation of ['doPreview', 'doRun', 'doCancel', 'doSweepPreview', 'doSweepRun', 'doSweepCancel']) {
    assert.match(
      run,
      new RegExp(`async function ${operation}\\(\\)[\\s\\S]*?const requestId = operationRequestRef\\.current\\.begin\\(\\)[\\s\\S]*?if \\(!operationIsCurrent\\(requestId\\)\\) return;`),
      `${operation} must current-check its async continuation`,
    );
  }

  assert.match(run, /await session\.runExecute\([\s\S]*if \(!operationIsCurrent\(requestId\)\) return;[\s\S]*startRunPolling\(started\.run_id\)/);
  assert.match(run, /await session\.sweepExecute\([\s\S]*if \(!operationIsCurrent\(requestId\)\) return;[\s\S]*startSweepPolling\(sweepPreview\.sweep_id\)/);
  assert.match(run, /function retryRunContext\(\)[\s\S]*operationRequestRef\.current\.invalidate\(\)[\s\S]*setContextGeneration/);
  assert.ok((run.match(/if \(!operationIsCurrent\(requestId\)\) return;/g) || []).length >= 12, 'success, catch, and finally continuations are guarded');
});

test('run and sweep polling invalidate stale generations and never overlap interval ticks', async () => {
  const run = await readRunSource();

  assert.match(run, /import \{[^}]*createRequestEpoch[^}]*\} from '\.\/requestEpoch'/);
  assert.match(run, /pollGenerationRef = useRef\(createRequestEpoch\(\)\)/);
  assert.match(run, /pollRequestRef = useRef\(createRequestEpoch\(\)\)/);
  assert.match(run, /function stopPolling\(\)[\s\S]*pollGenerationRef\.current\.invalidate\(\)[\s\S]*pollRequestRef\.current\.invalidate\(\)/);
  assert.match(run, /const generation = pollGenerationRef\.current\.begin\(\)/);
  assert.match(run, /const requestId = pollRequestRef\.current\.begin\(\)/);
  assert.ok((run.match(/pollGenerationRef\.current\.isCurrent\(generation\)/g) || []).length >= 4, 'both poll modes guard success and error paths');
  assert.ok((run.match(/pollRequestRef\.current\.isCurrent\(requestId\)/g) || []).length >= 4, 'every tick response is current-checked');
  assert.match(run, /window\.setTimeout\(\(\) => \{ void tick\(\); \}, 1500\)/);
  assert.doesNotMatch(run, /setInterval/);
  assert.match(run, /async function doCancel\(\)[\s\S]*stopPolling\(\)[\s\S]*await session\.runCancel\(runId\)/);
  assert.match(run, /async function doSweepCancel\(\)[\s\S]*stopPolling\(\)[\s\S]*await session\.sweepCancel\(sweepId\)/);
});

test('skeleton loading lanes use a visible telemetry scan and reduced motion stays static', async () => {
  const css = await read('../src/styles/controls.css');

  assert.match(css, /\.ui-skeleton-shape > span::after\s*\{[^}]*animation:\s*ui-skeleton-scan[^;]*var\(--dur-normal\)/s);
  assert.match(css, /@keyframes\s+ui-skeleton-scan\s*\{[^]*?transform:/s);
  assert.doesNotMatch(css, /\.ui-skeleton-shape > span\s*\{[^}]*background:\s*var\(--hairline-soft\)/s, 'loading lanes cannot fall back to grey rectangles');
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.ui-skeleton-shape > span::after[^}]*animation:\s*none/);
});
