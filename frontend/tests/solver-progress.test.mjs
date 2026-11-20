import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

import { effectiveSolverProgress, progressAttributes } from '../src/progressPresentation.mjs';
import { runStatusIsPollable, sweepStatusIsPollable } from '../src/runPolling.mjs';
import { readRunSource } from './run-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('semantic progress is determinate only for a valid explicit vendor fraction', () => {
  assert.deepEqual(progressAttributes(0.5, 50), { value: 0.5, max: 1 });
  for (const fraction of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, -0.1, 1.1]) {
    assert.deepEqual(progressAttributes(fraction, 50), { max: 1 });
  }
  assert.deepEqual(progressAttributes(0.5, null), { max: 1 });
  assert.deepEqual(progressAttributes(0.5, 75), { max: 1 });
});

test('poll failure overrides stale supervised presentation while preserving numeric evidence', () => {
  const supervised = {
    phase: 'running',
    liveness: 'supervised',
    simulation_time_s: 450,
    step: 2675,
    adaptive_total_steps: 12022,
    step_size_s: 0.25,
    vendor_percent: 50,
    fraction: 0.5,
  };

  const beforeFailure = effectiveSolverProgress(supervised, false);
  const afterFailure = effectiveSolverProgress(supervised, true);

  assert.equal(beforeFailure.liveness, 'supervised');
  assert.equal(afterFailure.liveness, 'supervision_unknown');
  assert.equal(afterFailure.phase, 'supervision_unknown');
  assert.equal(afterFailure.last_known, true);
  assert.equal(afterFailure.last_known_phase, 'running');
  assert.equal(afterFailure.simulation_time_s, 450);
  assert.equal(afterFailure.step, 2675);
  assert.equal(afterFailure.fraction, 0.5);
  assert.equal(supervised.liveness, 'supervised', 'presentation derivation must be side-effect free');
});

test('run and sweep pollability include finalizing, cancellation pending, and supervision unknown', () => {
  assert.equal(runStatusIsPollable({ state: 'running', cancel_requested: false }), true);
  assert.equal(runStatusIsPollable({ state: 'finalizing', cancel_requested: false }), true);
  assert.equal(runStatusIsPollable({ state: 'supervision_unknown', cancel_requested: false }), true);
  assert.equal(runStatusIsPollable({ state: 'completed', cancel_requested: true }), false);
  assert.equal(runStatusIsPollable({ state: 'completed', cancel_requested: false }), false);
  assert.equal(sweepStatusIsPollable({ state: 'finalizing', cases: [] }), true);
  assert.equal(sweepStatusIsPollable({ state: 'completed', cases: [{ state: 'completed', cancel_requested: true }] }), false);
  assert.equal(sweepStatusIsPollable({ state: 'completed', cases: [] }), false);
});

test('RunProgress separates process phase from output activity and never infers ETA', async () => {
  const [component, session, run, panel] = await Promise.all([
    read('../src/RunProgress.tsx'),
    readSessionSource(import.meta.url),
    readRunSource(),
    read('../src/RunFailurePanel.tsx'),
  ]);

  assert.match(session, /export interface SolverProgress/);
  assert.match(session, /readonly cancel_requested: boolean/);
  assert.match(component, /<progress/);
  assert.match(component, /progressAttributes\(effective\.fraction, effective\.vendor_percent\)/);
  assert.match(component, /effectiveSolverProgress\(progress, supervisionUnknown\)/);
  assert.match(component, /t\('run\.phase'\)/);
  assert.match(component, /t\('run\.activity'\)/);
  assert.match(component, /t\('run\.activity\.stale'\)/);
  assert.doesNotMatch(component, /stalled|dead/i);
  assert.doesNotMatch(component + run + panel, /\bETA\b|estimated time remaining/i);
});

test('RunView polls cancellation pending and supervision-unknown states until terminal authority arrives', async () => {
  const run = await readRunSource();

  assert.match(run, /import \{ runStatusIsPollable, sweepStatusIsPollable \} from '\.\/runPolling'/);
  assert.match(run, /const cancelled = await session\.runCancel\(runId\)[\s\S]*runStatusIsPollable\(cancelled\)[\s\S]*startRunPolling\(runId\)/);
  assert.match(run, /<RunProgress progress=\{liveStatus\.solver_progress\} cancelRequested=\{liveStatus\.cancel_requested\}/);
});

test('running status is not called live and terminal receipts are not rendered while running', async () => {
  const panel = await read('../src/RunFailurePanel.tsx');

  assert.doesNotMatch(panel, /state === 'running'[\s\S]{0,80}live/);
  assert.match(panel, /const hasRunEvidence = TERMINAL_RUN_STATES\.has\(status\.state\)/);
  assert.match(panel, /\{hasRunEvidence && \([\s\S]*<Receipt title=\{t\('run\.receipt'\)\}/);
});

test('sweep status exposes only counts globally and bounded per-case solver evidence', async () => {
  const [sweep, session] = await Promise.all([
    read('../src/RunSweepStatus.tsx'),
    readSessionSource(import.meta.url),
  ]);

  assert.match(session, /interface SweepCaseStatus[\s\S]*solver_progress: SolverProgress/);
  assert.match(sweep, /completedCount/);
  assert.match(sweep, /RunProgress/);
  assert.doesNotMatch(sweep, /aggregate.{0,20}(percent|fraction)|percent.{0,20}aggregate/i);
  assert.doesNotMatch(sweep, /\bETA\b|estimated time remaining/i);
});
