import assert from 'node:assert/strict';
import test from 'node:test';

import { patrolCardRenderer } from './helpers/render-patrol-card.mjs';
import { runProgressRenderer } from './helpers/render-run-progress.mjs';

const { renderCard, clearRunFinishStore } = await patrolCardRenderer();
const { renderProgress } = await runProgressRenderer();

// Solver progress without the adaptive_total_steps key: the field stays
// blank instead of showing an implausible 2^32-scale value.
const progressWithoutAdaptive = () => ({
  parse_status: 'parsed',
  activity_status: 'active',
  observed_at: '2026-01-01T00:00:00Z',
  file_timestamp: null,
  age_seconds: 3,
  simulation_time_s: 3060,
  step: 1812,
  step_size_s: 0.25,
  vendor_percent: 42.5,
  fraction: 0.425,
  phase: 'running',
  liveness: 'supervised',
  files: { out: null, run_log: null },
  evidence: { timestep: 'solver.out', vendor_percent: 'solver.out' },
});

const cardWithoutAdaptive = (runId) => ({
  run_id: runId,
  state: 'running',
  terminal: false,
  poll_count: 6,
  elapsed_ms: 4100,
  observations: [{
    vendor_percent: 42.5,
    simulation_time_s: 3060,
    step: 1812,
    phase: 'running',
    liveness: 'supervised',
  }],
});

test('L2-fe: a patrol card without adaptive_total_steps shows no adaptive row', () => {
  clearRunFinishStore();
  for (const locale of ['ko', 'en']) {
    const html = renderCard(locale, 'run_patrol', cardWithoutAdaptive(`run-l2-${locale}`));
    assert.doesNotMatch(html, /적응형 누적 스텝/);
    assert.doesNotMatch(html, /Adaptive total steps/);
    assert.match(html, /1812/);
  }
  clearRunFinishStore();
});

test('L2-fe: RunProgress without adaptive_total_steps shows the step but no estimate', () => {
  for (const locale of ['ko', 'en']) {
    const html = renderProgress(locale, progressWithoutAdaptive());
    assert.match(html, /1,812/);
    assert.doesNotMatch(html, /적응 추정/);
    assert.doesNotMatch(html, /adaptive estimate/);
  }
});

test('L2-fe: a null adaptive_total_steps also renders nothing', () => {
  clearRunFinishStore();
  const html = renderCard('ko', 'run_patrol', {
    ...cardWithoutAdaptive('run-l2-null'),
    observations: [{ ...cardWithoutAdaptive('run-l2-null').observations[0], adaptive_total_steps: null }],
  });
  assert.doesNotMatch(html, /적응형 누적 스텝/);
  assert.match(html, /1812/);
  clearRunFinishStore();
});
