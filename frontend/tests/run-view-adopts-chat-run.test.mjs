import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { runToAdopt } from '../src/runPolling.mjs';

// Live PVT 2026-11-16 (item 14): a run started from chat ran for 41 s while the open
// Run view stayed "준비됨" with no progress, no Stop and a live "승인하고 실행".
const running = (id) => ({ kind: 'run', status: { run_id: id, state: 'running' } });

test('a running run the view does not follow is adopted once', () => {
  const seen = new Set();
  assert.equal(runToAdopt(running('r2'), 'r1', seen), 'r2');
  assert.equal(runToAdopt(running('r2'), 'r1', seen), null, 'a second sighting does not reload again');
});

test('the run the view already follows, a finished run and a sweep are left alone', () => {
  assert.equal(runToAdopt(running('r1'), 'r1', new Set()), null);
  assert.equal(runToAdopt({ kind: 'run', status: { run_id: 'r3', state: 'completed' } }, null, new Set()), null);
  assert.equal(runToAdopt({ kind: 'sweep', status: { sweep_id: 's', state: 'running', cases: [] } }, null, new Set()), null);
});

test('the run lifecycle listens to the run feed and reloads its context for an adopted run', async () => {
  const source = await readFile(new URL('../src/useRunLifecycle.ts', import.meta.url), 'utf8');
  assert.match(source, /subscribeRunObservations\(/);
  assert.match(source, /runToAdopt\(/);
  assert.match(source, /setContextGeneration\(/);
});
