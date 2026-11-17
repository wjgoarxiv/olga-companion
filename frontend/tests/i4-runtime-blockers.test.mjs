import test from 'node:test';
import assert from 'node:assert/strict';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('latest active-case action ignores delayed success and error from superseded requests', async () => {
  const { createLatestAsyncAction } = await import('../src/latestAsync.mjs');
  const action = createLatestAsyncAction();
  const first = deferred();
  const second = deferred();
  let active = 'initial';
  const errors = [];

  const firstRun = action.run(() => first.promise, {
    onSuccess: (value) => { active = value; },
    onError: (error) => { errors.push(error.message); },
  });
  const secondRun = action.run(() => second.promise, {
    onSuccess: (value) => { active = value; },
    onError: (error) => { errors.push(error.message); },
  });

  second.resolve('B');
  await secondRun;
  first.resolve('A');
  await firstRun;
  assert.equal(active, 'B');

  const staleFailure = deferred();
  const current = deferred();
  const staleRun = action.run(() => staleFailure.promise, {
    onSuccess: (value) => { active = value; },
    onError: (error) => { errors.push(error.message); },
  });
  const currentRun = action.run(() => current.promise, {
    onSuccess: (value) => { active = value; },
    onError: (error) => { errors.push(error.message); },
  });
  current.resolve('C');
  await currentRun;
  staleFailure.reject(new Error('stale A failed'));
  await staleRun;

  assert.equal(active, 'C');
  assert.deepEqual(errors, []);
});

test('invalidating an active-case action prevents a pre-refresh response from committing', async () => {
  const { createLatestAsyncAction } = await import('../src/latestAsync.mjs');
  const action = createLatestAsyncAction();
  const pending = deferred();
  let active = 'refreshed';

  const run = action.run(() => pending.promise, {
    onSuccess: (value) => { active = value; },
    onError: () => { active = 'error'; },
  });
  action.invalidate();
  pending.resolve('stale');
  await run;

  assert.equal(active, 'refreshed');
});

test('active-case hydration loads topology without activation while one user click activates once', async () => {
  const { loadWorkspaceCase } = await import('../src/workspaceCaseOpen.mjs');
  const selectedCase = { name: 'case.genkey', rel: 'case.genkey', suffix: '.genkey', size: 10 };
  const activations = [];
  const topologyLoads = [];
  const dependencies = {
    activate: (rel) => { activations.push(rel); },
    fetchTopology: async (rel) => {
      topologyLoads.push(rel);
      return { path: rel, nodes: [], edges: [], counts: { nodes: 0, flowpaths: 0, edges: 0 }, truncated: false };
    },
  };

  await loadWorkspaceCase(selectedCase, { activate: false }, dependencies);
  await loadWorkspaceCase(selectedCase, { activate: false }, dependencies);
  assert.deepEqual(activations, [], 'remount hydration must not POST active-case selection');
  assert.deepEqual(topologyLoads, ['case.genkey', 'case.genkey'], 'each mounted view still hydrates topology');

  await loadWorkspaceCase(selectedCase, { activate: true }, dependencies);
  assert.deepEqual(activations, ['case.genkey'], 'one user click activates exactly once');
  assert.equal(topologyLoads.length, 3);
});

test('focus return runs after enablement and refuses a still-disabled or disconnected target', async () => {
  const { scheduleFocusReturn } = await import('../src/focusReturn.mjs');
  const queued = [];
  const schedule = (callback) => {
    queued.push(callback);
    return () => {};
  };
  let focused = 0;
  const target = {
    isConnected: true,
    disabled: true,
    matches(selector) { return selector.includes(':disabled') && this.disabled; },
    focus() { focused += 1; },
  };

  scheduleFocusReturn(target, schedule);
  assert.equal(focused, 0, 'focus is not attempted synchronously while React still exposes disabled state');
  target.disabled = false;
  queued.shift()();
  assert.equal(focused, 1, 'focus returns after the committed enabled state');

  scheduleFocusReturn(target, schedule);
  target.disabled = true;
  queued.shift()();
  target.disabled = false;
  target.isConnected = false;
  scheduleFocusReturn(target, schedule);
  queued.shift()();
  assert.equal(focused, 1);
});
