import assert from 'node:assert/strict';
import test from 'node:test';

import { patrolCardRenderer } from './helpers/render-patrol-card.mjs';

const { renderCard, publishRunFinish, clearRunFinishStore } = await patrolCardRenderer();

const runningResult = (runId) => ({
  run_id: runId,
  state: 'running',
  terminal: false,
  poll_count: 6,
  elapsed_ms: 4100,
  observations: [{
    vendor_percent: 42.5, simulation_time_s: 3060, step: 1812, phase: 'running', liveness: 'supervised',
  }],
});

test('FER10: a running receipt renders as running', () => {
  clearRunFinishStore();
  const html = renderCard('ko', 'run_patrol', runningResult('run-live-10'));
  assert.match(html, /실행 계속 중/);
  assert.doesNotMatch(html, /실행 완료/);
  clearRunFinishStore();
});

test('FER10: the same card renders finished after the store records the finish', () => {
  clearRunFinishStore();
  const result = runningResult('run-live-11');
  assert.match(renderCard('ko', 'run_patrol', result), /실행 계속 중/);
  publishRunFinish('run-live-11', 'completed');
  assert.match(renderCard('ko', 'run_patrol', result), /실행 완료/);
  assert.match(renderCard('en', 'run_patrol', result), /Run completed/);
  clearRunFinishStore();
});

test('FER10: a restored card mounts finished when the store already holds it', () => {
  clearRunFinishStore();
  publishRunFinish('run-live-12', 'completed');
  const html = renderCard('ko', 'run_patrol', runningResult('run-live-12'));
  assert.match(html, /실행 완료/);
  assert.doesNotMatch(html, /실행 계속 중/);
  clearRunFinishStore();
});

test('FER10: a restored failed card renders the failed title', () => {
  clearRunFinishStore();
  publishRunFinish('run-live-13', 'failed');
  const html = renderCard('ko', 'run_patrol', runningResult('run-live-13'));
  assert.match(html, /실행 실패함/);
  clearRunFinishStore();
});
