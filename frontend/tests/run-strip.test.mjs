// The run strip under the top bar: every screen can see how the current run is going.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runStripModel, STRIP_LINGER_MS } from '../src/runStripModel.mjs';

const progress = (over = {}) => ({
  parse_status: 'parsed', activity_status: 'active', simulation_time_s: 1200, step: 300,
  adaptive_total_steps: null, step_size_s: 4, vendor_percent: 33.3, fraction: 0.333,
  phase: 'running', liveness: 'supervised', ...over,
});
const run = (over = {}, prog = {}) => ({
  kind: 'run',
  status: { run_id: 'r1', state: 'running', elapsed_ms: 60_000, cancel_requested: false, source_name: 'hr01.genkey', solver_progress: progress(prog), ...over },
});

test('a running run shows percent, simulation time and time left', () => {
  const m = runStripModel(run(), { now: 0, terminalSince: null });
  assert.equal(m.visible, true);
  assert.equal(m.tone, 'running');
  assert.equal(m.percent, 33);
  assert.equal(m.simTimeS, 1200);
  // 60 s for a third: about 120 s left.
  assert.ok(m.etaS > 110 && m.etaS < 130, String(m.etaS));
  assert.equal(m.caseName, 'hr01.genkey');
  assert.equal(m.canStop, true);
});

test('no percent yet means an indeterminate bar and no time-left guess', () => {
  const m = runStripModel(run({}, { vendor_percent: null, fraction: null }), { now: 0, terminalSince: null });
  assert.equal(m.percent, null);
  assert.equal(m.etaS, null);
  assert.equal(m.visible, true);
});

test('a very early fraction gives no time-left guess', () => {
  const m = runStripModel(run({}, { vendor_percent: 0.5, fraction: 0.005 }), { now: 0, terminalSince: null });
  assert.equal(m.etaS, null);
});

test('a finished run stays visible for a while with an open-results action, then hides', () => {
  const done = run({ state: 'completed' }, { phase: 'terminal', liveness: 'terminal', activity_status: 'terminal', fraction: 1, vendor_percent: 100 });
  const shown = runStripModel(done, { now: 1000, terminalSince: 1000 });
  assert.equal(shown.visible, true);
  assert.equal(shown.tone, 'completed');
  assert.equal(shown.canStop, false);
  assert.equal(shown.canOpenResults, true);
  const later = runStripModel(done, { now: 1000 + STRIP_LINGER_MS + 1, terminalSince: 1000 });
  assert.equal(later.visible, false);
});

test('a failed run says so and offers the run screen, not results', () => {
  const m = runStripModel(run({ state: 'failed' }, { phase: 'terminal', activity_status: 'terminal' }), { now: 0, terminalSince: 0 });
  assert.equal(m.tone, 'failed');
  assert.equal(m.canOpenResults, false);
});

test('a requested cancel cannot be asked again', () => {
  const m = runStripModel(run({ cancel_requested: true }), { now: 0, terminalSince: null });
  assert.equal(m.canStop, false);
  assert.equal(m.tone, 'stopping');
});

test('an unconfirmed run is shown as unknown, not as progressing', () => {
  const m = runStripModel(run({ state: 'supervision_unknown' }), { now: 0, terminalSince: null });
  assert.equal(m.tone, 'unknown');
  assert.equal(m.etaS, null);
});

test('sweeps and empty observations hide the strip', () => {
  assert.equal(runStripModel(null, { now: 0, terminalSince: null }).visible, false);
  assert.equal(runStripModel({ kind: 'sweep', status: {} }, { now: 0, terminalSince: null }).visible, false);
});

test('the shell mounts the strip under the step bar and both languages carry its words', () => {
  const app = readFileSync(new URL('../src/shell/StepBarSlot.tsx', import.meta.url), 'utf8');
  assert.match(app, /<RunStrip\b/);
  const ko = readFileSync(new URL('../src/i18n/ko.ts', import.meta.url), 'utf8');
  const en = readFileSync(new URL('../src/i18n/en.ts', import.meta.url), 'utf8');
  for (const key of ['runStrip.running', 'runStrip.completed', 'runStrip.failed', 'runStrip.open', 'runStrip.results', 'runStrip.stop', 'runStrip.eta', 'runStrip.simTime']) {
    assert.ok(ko.includes(`'${key}'`), `ko ${key}`);
    assert.ok(en.includes(`'${key}'`), `en ${key}`);
  }
});

test('the strip enters once, marks its outcome once and keeps motion behind the motion setting', () => {
  const motion = readFileSync(new URL('../src/styles/motion.css', import.meta.url), 'utf8');
  assert.match(motion, /html\[data-motion="full"\] \.run-strip\[data-tone="completed"\]::before/);
  assert.match(motion, /@keyframes run-strip-wipe/);
  assert.match(motion, /run-strip-enter var\(--d-enter\) var\(--ease-enter\)/);
  assert.doesNotMatch(motion, /run-strip-(wipe|mark|enter)[^;]*infinite/, 'outcome marks play once');
  assert.match(readFileSync(new URL('../src/RunStrip.tsx', import.meta.url), 'utf8'), /<RollingNumber/);
});
