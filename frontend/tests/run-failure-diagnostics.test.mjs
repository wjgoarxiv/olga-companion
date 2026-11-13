import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';
import { readResultsSource } from './results-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('run failure is actionable and explicitly avoids automatic retry', async () => {
  const run = await readRunSource();
  const panel = await read('../src/RunFailurePanel.tsx');
  assert.match(run, /RunFailurePanel/);
  assert.match(panel, /t\('run\.autoRetryOff'\)/);
  assert.match(panel, /failure\.action/);
  assert.match(panel, /failure\.detail/);
});

test('the failure panel shows the stop notice instead of the stored failure for a cancelled or timed-out run', async () => {
  const panel = await read('../src/RunFailurePanel.tsx');
  assert.match(panel, /runStopNotice\(status, t\)/);
  assert.match(panel, /stopNotice \? \(/);
});

test('solver log tail has an explicit accessible name', async () => {
  const panel = await read('../src/RunFailurePanel.tsx');
  assert.match(panel, /<pre className="run-log" aria-label=\{t\('run\.solverLogAria'\)\}>/);
});

test('results inventory shows an honest loading state while the bounded scan runs', async () => {
  const results = await readResultsSource(import.meta.url);
  assert.match(results, /t\('results\.scanning'\)/);
  assert.match(results, /setLoading\(true\)/);
  assert.match(results, /setLoading\(false\)/);
});
