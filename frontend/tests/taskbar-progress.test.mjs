import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { createTaskbarDriver, taskbarFrameForRun, taskbarFrameForSweep, TASKBAR_ERROR_HOLD_MS } from '../src/taskbarProgress.mjs';
import { startTaskbarFollow } from '../src/taskbarFollow.mjs';
import { applyTaskbarProgress } from '../src/taskbarProgressWindow.mjs';
import {
  claimTaskbarPoll,
  getTaskbarTarget,
  publishTaskbarObservation,
  rememberTaskbarTarget,
  releaseTaskbarPoll,
  resetTaskbarRunFeed,
} from '../src/taskbarRunFeed.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function progress(fraction, vendor = fraction == null ? null : fraction * 100) {
  return { fraction, vendor_percent: vendor };
}

function run(state, fraction, extra = {}) {
  return {
    run_id: 'run-1',
    state,
    cancel_requested: false,
    solver_progress: progress(fraction),
    ...extra,
  };
}

test('running with a known fraction is normal percent', () => {
  assert.deepEqual(taskbarFrameForRun(run('running', 0.42)), { status: 'normal', progress: 42 });
  assert.deepEqual(taskbarFrameForRun(run('running', 0)), { status: 'normal', progress: 0 });
  assert.deepEqual(taskbarFrameForRun(run('finalizing', 1)), { status: 'normal', progress: 100 });
  assert.deepEqual(
    taskbarFrameForRun(run('supervision_unknown', 0.25)),
    { status: 'normal', progress: 25 },
  );
});

test('running without a known fraction is indeterminate', () => {
  assert.deepEqual(taskbarFrameForRun(run('running', null)), { status: 'indeterminate' });
  assert.deepEqual(taskbarFrameForRun(run('running', 0.5, { solver_progress: progress(0.5, 40) })), { status: 'indeterminate' });
  assert.deepEqual(taskbarFrameForRun({ state: 'running', cancel_requested: false }), { status: 'indeterminate' });
});

test('a running cancel request stays on the progress bar until the run actually stops', () => {
  assert.deepEqual(
    taskbarFrameForRun(run('running', 0.1, { cancel_requested: true })),
    { status: 'normal', progress: 10 },
  );
});

test('finished clears, failed and stopped go red', () => {
  assert.deepEqual(taskbarFrameForRun(run('completed', 1)), { status: 'none' });
  for (const state of ['failed', 'cancelled', 'timed_out', 'stopped']) {
    assert.deepEqual(taskbarFrameForRun(run(state, 0.2)), { status: 'error' }, state);
  }
  assert.deepEqual(taskbarFrameForRun(run('recovery_unknown', null)), { status: 'none' });
});

test('a sweep uses completed cases plus the active fraction', () => {
  const status = {
    sweep_id: 'sweep-1',
    state: 'running',
    cases: [
      { state: 'completed', solver_progress: progress(1) },
      { state: 'running', solver_progress: progress(0.5) },
    ],
  };
  assert.deepEqual(taskbarFrameForSweep(status), { status: 'normal', progress: 75 });
  status.cases[1] = { state: 'running', solver_progress: progress(null) };
  assert.deepEqual(taskbarFrameForSweep(status), { status: 'indeterminate' });
  assert.deepEqual(taskbarFrameForSweep({ state: 'completed', sweep_id: 'sweep-1', cases: [] }), { status: 'none' });
  assert.deepEqual(taskbarFrameForSweep({ state: 'failed', sweep_id: 'sweep-1', cases: [] }), { status: 'error' });
  assert.deepEqual(taskbarFrameForSweep({ state: 'cancelled', sweep_id: 'sweep-1', cases: [] }), { status: 'error' });
});

test('percent updates wait a second, status changes do not, error clears itself', () => {
  let now = 0;
  const applied = [];
  const driver = createTaskbarDriver({ now: () => now, apply: (frame) => applied.push(frame) });
  driver.reset();
  driver.observe({ status: 'normal', progress: 10 });
  now = 500;
  driver.observe({ status: 'normal', progress: 20 });
  now = 1000;
  driver.observe({ status: 'normal', progress: 20 });
  driver.observe({ status: 'none' });
  assert.deepEqual(applied, [
    { status: 'none' },
    { status: 'normal', progress: 10 },
    { status: 'normal', progress: 20 },
    { status: 'none' },
  ]);

  applied.length = 0;
  now = 0;
  driver.reset();
  driver.observe({ status: 'error' });
  now = 1000;
  driver.observe({ status: 'error' });
  driver.tick();
  now = TASKBAR_ERROR_HOLD_MS;
  driver.tick();
  assert.deepEqual(applied, [
    { status: 'none' },
    { status: 'error' },
    { status: 'none' },
  ]);
});

test('a new run replaces the red bar immediately', () => {
  let now = 0;
  const applied = [];
  const driver = createTaskbarDriver({ now: () => now, apply: (frame) => applied.push(frame) });
  driver.reset();
  driver.observe({ status: 'error' });
  now = 200;
  driver.observe({ status: 'normal', progress: 0 });
  now = TASKBAR_ERROR_HOLD_MS;
  driver.tick();
  assert.deepEqual(applied.at(-1), { status: 'normal', progress: 0 });
});

test('the taskbar call is a no-op outside Tauri and does not throw', async () => {
  await applyTaskbarProgress({ status: 'normal', progress: 40 });
  await applyTaskbarProgress({ status: 'none' });
  await applyTaskbarProgress(null);
});

function harness(overrides = {}) {
  resetTaskbarRunFeed();
  overrides.prepare?.();
  const applied = [];
  const polls = [];
  let scheduled = null;
  let discoveries = 0;
  const stop = startTaskbarFollow({
    now: () => 0,
    apply: (frame) => applied.push(frame),
    schedule: (_ms, fn) => { scheduled = fn; },
    cancelSchedule: () => { scheduled = null; },
    discover: async () => {
      discoveries += 1;
      return overrides.discover ? overrides.discover() : null;
    },
    pollRun: async (id) => {
      polls.push(['run', id]);
      return overrides.pollRun ? overrides.pollRun(id) : { kind: 'run', status: run('running', 0.5) };
    },
    pollSweep: async (id) => {
      polls.push(['sweep', id]);
      return overrides.pollSweep(id);
    },
  });
  return {
    applied,
    polls,
    discoveries: () => discoveries,
    runScheduled: async () => {
      const fn = scheduled;
      scheduled = null;
      await fn();
    },
    stop,
  };
}

const settled = () => new Promise((resolve) => setTimeout(resolve, 0));

test('a claimed poller owns the bar; the follower does not fetch again', async () => {
  const h = harness({
    prepare: () => {
      rememberTaskbarTarget({ kind: 'run', id: 'run-1' });
      claimTaskbarPoll('lifecycle', { kind: 'run', id: 'run-1' });
    },
  });
  await settled();
  assert.deepEqual(h.polls, []);
  publishTaskbarObservation({ kind: 'run', status: run('running', 0.4) });
  assert.deepEqual(h.applied.at(-1), { status: 'normal', progress: 40 });
  h.stop();
  resetTaskbarRunFeed();
});

test('the follower polls only after the claim drops, and stops when the run ends', async () => {
  let phase = 'running';
  const h = harness({
    prepare: () => {
      rememberTaskbarTarget({ kind: 'run', id: 'run-1' });
      claimTaskbarPoll('lifecycle', { kind: 'run', id: 'run-1' });
    },
    pollRun: () => ({
      kind: 'run',
      status: phase === 'running' ? run('running', 0.5) : run('failed', 0.5),
    }),
  });
  await settled();
  assert.deepEqual(h.polls, []);
  releaseTaskbarPoll('lifecycle');
  await h.runScheduled();
  assert.deepEqual(h.polls, [['run', 'run-1']]);
  phase = 'failed';
  await h.runScheduled();
  assert.equal(h.polls.length, 2);
  assert.equal(getTaskbarTarget(), null);
  await h.runScheduled();
  assert.equal(h.polls.length, 2, 'a finished run is not polled again');
  assert.deepEqual(h.applied.at(-1), { status: 'error' });
  h.stop();
  resetTaskbarRunFeed();
});

test('startup discovery reads history once and does not poll on that same tick', async () => {
  const h = harness({
    discover: async () => ({ kind: 'run', id: 'run-9', status: { ...run('running', 0.2), run_id: 'run-9' } }),
  });
  await settled();
  assert.equal(h.discoveries(), 1);
  assert.deepEqual(h.polls, []);
  assert.deepEqual(h.applied.at(-1), { status: 'normal', progress: 20 });
  await h.runScheduled();
  assert.equal(h.discoveries(), 1);
  assert.deepEqual(h.polls, [['run', 'run-9']]);
  h.stop();
  resetTaskbarRunFeed();
});

test('a sweep left running is followed when Run view releases it', async () => {
  const h = harness({
    prepare: () => {
      rememberTaskbarTarget({ kind: 'sweep', id: 'sweep-1' });
    },
    pollSweep: () => ({
      kind: 'sweep',
      status: {
        sweep_id: 'sweep-1',
        state: 'running',
        cases: [
          { state: 'completed', solver_progress: progress(1) },
          { state: 'running', solver_progress: progress(0) },
        ],
      },
    }),
  });
  await settled();
  assert.deepEqual(h.polls, [['sweep', 'sweep-1']]);
  assert.deepEqual(h.applied.at(-1), { status: 'normal', progress: 50 });
  h.stop();
  resetTaskbarRunFeed();
});

test('taskbar wiring stays on the existing pollers and keeps the attention flash', async () => {
  const [caps, away, layer, lifecycle, opener, card, runApi, sweepApi] = await Promise.all([
    read('../../src-tauri/capabilities/default.json'),
    read('../src/awayNotify.mjs'),
    read('../src/AppLifecycleLayer.tsx'),
    read('../src/useRunLifecycle.ts'),
    read('../src/useRunCompletionOpener.ts'),
    read('../src/LifecycleEvidence.tsx'),
    read('../src/runApi.ts'),
    read('../src/sweepApi.ts'),
  ]);
  const permissions = JSON.parse(caps).permissions;
  assert.ok(permissions.includes('core:window:allow-set-progress-bar'));
  assert.ok(permissions.includes('core:window:allow-request-user-attention'));
  assert.match(away, /export async function flashTaskbarDefault/);
  assert.match(away, /requestUserAttention/);
  assert.match(layer, /useTaskbarProgress\(workspaceRoot\)/);
  assert.match(lifecycle, /claimTaskbarPoll\('lifecycle'/);
  assert.match(lifecycle, /releaseTaskbarPoll\('lifecycle'\)/);
  assert.match(lifecycle, /rememberTaskbarTarget\(\{ kind: 'run', id \}\)/);
  assert.match(lifecycle, /rememberTaskbarTarget\(\{ kind: 'sweep', id \}\)/);
  assert.match(opener, /claimTaskbarPoll\(owner, \{ kind: 'run', id: runId \}\)/);
  assert.match(card, /pollStatus: runStatus/);
  assert.match(card, /claimTaskbarPoll\(owner, \{ kind: 'run', id: runId \}\)/);
  assert.match(runApi, /publishTaskbarObservation\(\{ kind: 'run', status: normalized \}\)/);
  assert.match(sweepApi, /publishTaskbarObservation\(\{ kind: 'sweep', status \}\)/);
});
