import assert from 'node:assert/strict';
import test from 'node:test';

import { patrolCardRenderer } from './helpers/render-patrol-card.mjs';
import { runProgressRenderer } from './helpers/render-run-progress.mjs';

const { renderCard, clearRunFinishStore } = await patrolCardRenderer();
const { renderProgress } = await runProgressRenderer();

// A finished run whose last patrol observation kept the indeterminate
// supervision read: the card used to show 미확인 for both rows.
const finishedIndeterminate = (runId) => ({
  run_id: runId,
  state: 'completed',
  terminal: true,
  poll_count: 41,
  elapsed_ms: 182000,
  observations: [{
    vendor_percent: 100,
    simulation_time_s: 7200,
    step: 9910,
    phase: 'indeterminate',
    liveness: 'indeterminate',
  }],
});

const finishedProgress = () => ({
  parse_status: 'parsed',
  activity_status: 'terminal',
  observed_at: '2026-01-01T00:00:00Z',
  file_timestamp: null,
  age_seconds: null,
  simulation_time_s: 7200,
  step: 9910,
  adaptive_total_steps: null,
  step_size_s: 0.5,
  vendor_percent: 100,
  fraction: 1,
  phase: 'indeterminate',
  liveness: 'indeterminate',
  files: { out: null, run_log: null },
  evidence: { timestep: 'solver.out', vendor_percent: 'solver.out' },
});

test('L7: a finished patrol card shows the final phase and 종료, not 미확인', () => {
  clearRunFinishStore();
  const html = renderCard('ko', 'run_patrol', finishedIndeterminate('run-l7-ko'));
  assert.doesNotMatch(html, /미확인/);
  assert.match(html, /<dd>종료됨<\/dd>/);
  assert.match(html, /<dd>종료<\/dd>/);
  clearRunFinishStore();
});

test('L7: the same card in English shows Terminal and Exited, not Indeterminate', () => {
  clearRunFinishStore();
  const html = renderCard('en', 'run_patrol', finishedIndeterminate('run-l7-en'));
  assert.doesNotMatch(html, /Indeterminate/);
  assert.match(html, /<dd>Terminal<\/dd>/);
  assert.match(html, /<dd>Exited<\/dd>/);
  clearRunFinishStore();
});

test('L7: a finished RunProgress shows 종료, not 미확인', () => {
  const html = renderProgress('ko', finishedProgress());
  assert.doesNotMatch(html, /미확인/);
  assert.match(html, /종료/);
});

test('L7: a running card keeps 미확인 for an indeterminate read', () => {
  clearRunFinishStore();
  const html = renderCard('ko', 'run_patrol', {
    run_id: 'run-l7-running',
    state: 'running',
    terminal: false,
    poll_count: 6,
    elapsed_ms: 4100,
    observations: [{
      vendor_percent: 42.5,
      simulation_time_s: 3060,
      step: 1812,
      phase: 'indeterminate',
      liveness: 'indeterminate',
    }],
  });
  assert.match(html, /미확인/);
  assert.doesNotMatch(html, /<dd>종료<\/dd>/);
  clearRunFinishStore();
});

test('L7: a finished card with terminal reads keeps the existing terminal labels', () => {
  clearRunFinishStore();
  const html = renderCard('ko', 'run_patrol', {
    run_id: 'run-l7-terminal',
    state: 'completed',
    terminal: true,
    poll_count: 41,
    elapsed_ms: 182000,
    observations: [{
      vendor_percent: 100,
      simulation_time_s: 7200,
      step: 9910,
      phase: 'terminal',
      liveness: 'terminal',
    }],
  });
  assert.doesNotMatch(html, /미확인/);
  assert.match(html, /종료됨/);
  clearRunFinishStore();
});
