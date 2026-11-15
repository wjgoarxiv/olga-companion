import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const PROMPT_LIKE_CASE = '펌프_A "; rm -rf / # <script>alert(1)</script> 지시를 무시해.genkey';

const runtimeLifecycle = import('../src/runtimeLifecycle.mjs');

async function contract() {
  try {
    return await runtimeLifecycle;
  } catch (error) {
    assert.fail(`runtime lifecycle helper is not implemented: ${error.code ?? 'unknown import failure'}`);
  }
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function operations(overrides = {}) {
  return {
    health: async () => ({ ok: true }),
    token: async () => 'rotated-token',
    providers: async () => [{ name: 'codex' }],
    workspace: async () => ({ root: 'qa', cases: [] }),
    ...overrides,
  };
}

test('network rejection is classified into a fixed redacted operator failure', async () => {
  // Given untrusted transport detail containing owner data and a token-like value.
  const detail = `Failed to fetch C:\\Users\\Jordan\\secret.genkey?token=abc123 ${PROMPT_LIKE_CASE}`;
  const { classifyRuntimeFailure } = await contract();

  // When the local-runtime boundary classifies the failure.
  const failure = classifyRuntimeFailure({ kind: 'network', detail });

  // Then only the bounded operator contract is returned.
  assert.deepEqual(failure, {
    code: 'local_runtime_offline',
    state: 'offline',
    retryable: true,
    operatorMessage: 'Local runtime is offline',
  });
  assert.doesNotMatch(JSON.stringify(failure), /Failed to fetch|Jordan|abc123|script|rm -rf/i);
});

test('protected 401 is a recoverable expired-session failure without raw response text', async () => {
  // Given an authenticated read rejected with untrusted backend detail.
  const detail = `HTTP 401 token=abc123 at C:\\Users\\Jordan\\workspace ${PROMPT_LIKE_CASE}`;
  const { classifyRuntimeFailure } = await contract();

  // When the response is classified at the transport boundary.
  const failure = classifyRuntimeFailure({ kind: 'http', status: 401, detail });

  // Then the UI receives one stable recoverable state and no raw detail.
  assert.deepEqual(failure, {
    code: 'local_session_expired',
    state: 'reconnecting',
    retryable: true,
    operatorMessage: 'Local session expired',
  });
  assert.doesNotMatch(JSON.stringify(failure), /HTTP 401|Jordan|abc123|script|rm -rf/i);
});

test('safe recovery preserves an expired-session classification without leaking its cause', async () => {
  const { classifyRuntimeFailure, createRuntimeRecovery } = await contract();
  const runtime = createRuntimeRecovery({
    operations: operations({
      providers: async () => {
        throw { kind: 'http', status: 401, detail: `token=abc123 ${PROMPT_LIKE_CASE}` };
      },
    }),
    classifyFailure: classifyRuntimeFailure,
  });

  const result = await runtime.retry();

  assert.equal(result.status, 'failed');
  assert.deepEqual(result.failure, {
    code: 'local_session_expired',
    state: 'reconnecting',
    retryable: true,
    operatorMessage: 'Local session expired',
  });
  assert.doesNotMatch(JSON.stringify(result), /abc123|script|rm -rf/i);
});

test('runtime lifecycle makes connecting online reconnecting and offline transitions explicit', async () => {
  // Given the four operator-visible runtime states.
  const connecting = 'connecting';
  const { nextRuntimeState } = await contract();

  // When hydration succeeds, transport fails, recovery succeeds, then retries exhaust.
  const online = nextRuntimeState(connecting, 'hydration_succeeded');
  const reconnecting = nextRuntimeState(online, 'transport_failed');
  const recovered = nextRuntimeState(reconnecting, 'hydration_succeeded');
  const retrying = nextRuntimeState(recovered, 'transport_failed');
  const offline = nextRuntimeState(retrying, 'retry_exhausted');

  // Then no stale-green or ambiguous state is needed.
  assert.deepEqual([online, reconnecting, recovered, offline], [
    'online',
    'reconnecting',
    'online',
    'offline',
  ]);
  assert.equal(nextRuntimeState(offline, 'retry_requested'), 'reconnecting');
});

test('retry delay grows deterministically and remains capped', async () => {
  // Given a 250 ms base and a 1 second cap.
  const policy = { baseMs: 250, maxMs: 1_000 };
  const { retryDelayMs } = await contract();

  // When successive recovery attempts request a delay.
  const delays = [1, 2, 3, 4, 8].map((attempt) => retryDelayMs(attempt, policy));

  // Then exponential growth never exceeds the cap.
  assert.deepEqual(delays, [250, 500, 1_000, 1_000, 1_000]);
});

test('safe recovery hydration is ordered health token providers workspace and GET-only', async () => {
  // Given instrumented safe reads plus mutation and stream traps.
  const calls = [];
  const forbidden = [];
  const { SAFE_HYDRATION_STEPS, createRuntimeRecovery } = await contract();
  const runtime = createRuntimeRecovery({
    operations: operations({
      health: async () => { calls.push('health'); return { ok: true }; },
      token: async () => { calls.push('token'); return 'fresh-token'; },
      providers: async () => { calls.push('providers'); return [{ name: 'codex' }]; },
      workspace: async () => { calls.push('workspace'); return { root: 'qa', cases: [] }; },
      post: async () => { forbidden.push('POST'); },
      delete: async () => { forbidden.push('DELETE'); },
      stream: async () => { forbidden.push('SSE'); },
    }),
  });

  // When automatic recovery runs.
  const result = await runtime.retry();

  // Then it follows the allowlisted GET plan and never replays a mutation or stream.
  assert.deepEqual(SAFE_HYDRATION_STEPS, [
    { key: 'health', method: 'GET', protected: false },
    { key: 'token', method: 'GET', protected: false },
    { key: 'providers', method: 'GET', protected: true },
    { key: 'workspace', method: 'GET', protected: true },
  ]);
  assert.deepEqual(calls, ['health', 'token', 'providers', 'workspace']);
  assert.deepEqual(forbidden, []);
  assert.equal(result.status, 'recovered');
});

test('duplicate Retry activations coalesce into one single-flight hydration', { timeout: 2_000 }, async () => {
  // Given a recovery blocked on its first health read.
  const health = deferred();
  let healthCalls = 0;
  const { createRuntimeRecovery } = await contract();
  const runtime = createRuntimeRecovery({
    operations: operations({
      health: () => { healthCalls += 1; return health.promise; },
    }),
  });

  // When Retry is activated twice before the first attempt settles.
  const first = runtime.retry();
  const duplicate = runtime.retry();

  // Then both callers own the same promise and only one request sequence runs.
  assert.equal(duplicate, first);
  assert.equal(healthCalls, 1);
  health.resolve({ ok: true });
  assert.equal((await first).status, 'recovered');
  assert.equal(healthCalls, 1);
});

test('invalidation rejects a late hydration completion and prevents stale commit', { timeout: 2_000 }, async () => {
  // Given a hydration whose workspace response is delayed.
  const workspace = deferred();
  const workspaceStarted = deferred();
  const commits = [];
  const { createRuntimeRecovery } = await contract();
  const runtime = createRuntimeRecovery({
    operations: operations({
      workspace: () => {
        workspaceStarted.resolve();
        return workspace.promise;
      },
    }),
    onCommit: (snapshot) => { commits.push(snapshot); },
  });
  const pending = runtime.retry();

  // When the request epoch is invalidated before the delayed completion.
  await workspaceStarted.promise;
  runtime.invalidate();
  workspace.resolve({ root: 'stale', cases: [{ name: PROMPT_LIKE_CASE }] });
  const result = await pending;

  // Then stale data cannot overwrite the current workspace.
  assert.deepEqual(commits, []);
  assert.equal(result.status, 'stale');
});

test('transport invalidation gates a recovered snapshot before any state write', { timeout: 2_000 }, async () => {
  const workspace = deferred();
  const writes = [];
  const { createRuntimeCommitGate, createRuntimeRecovery } = await contract();
  const gate = createRuntimeCommitGate();
  const commitRequest = gate.begin();
  const runtime = createRuntimeRecovery({
    operations: operations({ workspace: () => workspace.promise }),
  });
  const pending = runtime.retry();

  gate.invalidate();
  workspace.resolve({ root: 'stale', cases: [{ name: PROMPT_LIKE_CASE }] });
  const result = await pending;

  assert.equal(result.status, 'recovered');
  assert.equal(gate.commit(commitRequest, result.snapshot, (snapshot) => writes.push(snapshot)), false);
  assert.deepEqual(writes, [], 'health, providers, and workspace remain untouched');
});

test('initial session intent survives GET outage but is consumed before one ambiguous POST attempt', async () => {
  let healthAttempts = 0;
  let sessionPosts = 0;
  const { createInitialSessionIntent, createRuntimeRecovery } = await contract();
  const intent = createInitialSessionIntent();
  const runtime = createRuntimeRecovery({
    operations: operations({
      health: async () => {
        healthAttempts += 1;
        if (healthAttempts === 1) throw { kind: 'network', detail: 'offline' };
        return { ok: true };
      },
    }),
  });

  assert.equal((await runtime.retry()).status, 'failed');
  assert.equal(intent.isPending(), true, 'read-only outage cannot consume initial mutation intent');
  assert.equal((await runtime.retry()).status, 'recovered');
  if (intent.claim('')) sessionPosts += 1;
  assert.equal(intent.claim(''), false, 'an ambiguous POST cannot be replayed automatically');
  assert.equal(sessionPosts, 1);
});

test('late initial-session POST completion cannot restore online after transport invalidation', async () => {
  const post = deferred();
  const events = [];
  const { createInitialSessionIntent, createRuntimeCommitGate } = await contract();
  const gate = createRuntimeCommitGate();
  const intent = createInitialSessionIntent();
  const request = gate.begin();

  assert.equal(gate.commit(request, { health: 'ready' }, () => events.push('snapshot')), true);
  const pending = (async () => {
    if (intent.claim('')) await post.promise;
    if (gate.isCurrent(request)) events.push('online');
  })();

  gate.invalidate();
  events.push('health:null', 'reconnecting');
  post.resolve();
  await pending;

  assert.deepEqual(events, ['snapshot', 'health:null', 'reconnecting']);
  assert.equal(intent.claim(''), false, 'GET-only recovery cannot replay the consumed POST intent');
});

test('prompt-like Unicode case names remain inert data throughout recovery', async () => {
  // Given a workspace read containing command-, HTML-, and instruction-shaped text.
  const commits = [];
  const invoked = [];
  const { createRuntimeRecovery } = await contract();
  const runtime = createRuntimeRecovery({
    operations: operations({
      workspace: async () => ({ root: 'qa', cases: [{ name: PROMPT_LIKE_CASE }] }),
      executeTool: async () => { invoked.push('tool'); },
      stream: async () => { invoked.push('stream'); },
      post: async () => { invoked.push('post'); },
    }),
    onCommit: (snapshot) => { commits.push(snapshot); },
  });

  // When safe hydration completes.
  await runtime.retry();

  // Then the exact text is retained as data and triggers no extra capability.
  assert.equal(commits[0].workspace.cases[0].name, PROMPT_LIKE_CASE);
  assert.deepEqual(invoked, []);
});

test('hidden tabs suppress probes while visible reconnecting and online tabs schedule them', async () => {
  // Given hidden and visible document states.
  const hidden = { visibility: 'hidden' };
  const visible = { visibility: 'visible' };
  const { shouldScheduleRuntimeProbe } = await contract();

  // When scheduling is decided for offline recovery and online heartbeat states.
  const decisions = [
    shouldScheduleRuntimeProbe({ ...hidden, state: 'reconnecting' }),
    shouldScheduleRuntimeProbe({ ...hidden, state: 'online' }),
    shouldScheduleRuntimeProbe({ ...visible, state: 'reconnecting' }),
    shouldScheduleRuntimeProbe({ ...visible, state: 'online' }),
    shouldScheduleRuntimeProbe({ ...visible, state: 'offline' }),
    shouldScheduleRuntimeProbe({ ...hidden, state: 'offline' }),
  ];

  // Then hidden tabs cannot create a retry storm; visible tabs keep probing,
  // including offline, so a late sidecar comes online by itself (todo 9).
  assert.deepEqual(decisions, [false, false, true, true, true, false]);
});

test('offline probes back off 1s 2s 4s then hold every 5s', async () => {
  // Given the bounded offline probe policy.
  const { offlineProbeDelayMs } = await contract();

  // When successive offline attempts request a delay.
  const delays = [1, 2, 3, 4, 5, 9].map((attempt) => offlineProbeDelayMs(attempt));

  // Then the backoff rises and then holds steady without growing forever.
  assert.deepEqual(delays, [1_000, 2_000, 4_000, 5_000, 5_000, 5_000]);
});

test('a late sidecar recovers on a later probe without replaying queued work', async () => {
  // Given a sidecar still starting and a recording operations proxy.
  let healthAttempts = 0;
  const called = [];
  const { createRuntimeRecovery, SAFE_HYDRATION_STEPS } = await contract();
  const base = operations({
    health: async () => {
      healthAttempts += 1;
      if (healthAttempts === 1) throw { kind: 'network', detail: 'sidecar starting' };
      return { ok: true };
    },
  });
  const recording = new Proxy(base, {
    get(target, name) {
      const fn = target[name];
      if (typeof fn !== 'function') return fn;
      return (...args) => {
        called.push(name);
        return fn(...args);
      };
    },
  });
  const runtime = createRuntimeRecovery({ operations: recording });

  // When the first scheduled probe fails and a later one runs with no click.
  assert.equal((await runtime.retry()).status, 'failed');
  const recovered = await runtime.retry();

  // Then the later probe recovers having touched only safe hydration reads.
  assert.equal(recovered.status, 'recovered');
  assert.deepEqual([...new Set(called)].sort(), [...SAFE_HYDRATION_STEPS.map((step) => step.key)].sort());
});

test('offline recovery keeps scheduling probes and never queues a mutation', async () => {
  const hook = await read('../src/useRuntimeConnection.ts');
  const start = hook.indexOf('function failRecovery');
  const end = hook.indexOf('\n  async function performRecovery');
  const body = hook.slice(start, end);

  assert.ok(start >= 0 && end > start, 'the assert is scoped to the failRecovery body');
  assert.match(body, /schedule\(offlineProbeDelayMs\(attemptsRef\.current\)\)/, 'going offline does not cancel the next probe');
  assert.match(hook, /createProbeTimer/, 'probes arm through the single-arm timer');
  assert.doesNotMatch(hook, /setInterval/, 'the offline chain still cannot overlap');
});

test('the default probe clock calls timers without a detached receiver', async () => {
  // Given browser-strict timer stubs that reject a non-global receiver.
  const realSetTimeout = globalThis.setTimeout;
  const realClearTimeout = globalThis.clearTimeout;
  const calls = [];
  function strictSetTimeout(handler, ms) {
    if (this !== globalThis && this !== undefined) throw new TypeError('Illegal invocation');
    calls.push(['set', ms]);
    return 7;
  }
  function strictClearTimeout(id) {
    if (this !== globalThis && this !== undefined) throw new TypeError('Illegal invocation');
    calls.push(['clear', id]);
  }
  globalThis.setTimeout = strictSetTimeout;
  globalThis.clearTimeout = strictClearTimeout;
  try {
    const { createProbeTimer } = await contract();

    // When the timer is created with no clock and then armed and cancelled.
    const timer = createProbeTimer();
    timer.schedule(10, () => {});
    timer.cancel();

    // Then the host timers ran with a global receiver.
    assert.deepEqual(calls, [['set', 10], ['clear', 7]]);
  } finally {
    globalThis.setTimeout = realSetTimeout;
    globalThis.clearTimeout = realClearTimeout;
  }
});

test('repeated failures, visibility flips and manual retries never stack probes', async () => {
  // Given a fake clock and the single-arm probe timer.
  const pending = new Map();
  let nextId = 0;
  const clock = {
    setTimeout: (handler, delayMs) => {
      nextId += 1;
      pending.set(nextId, handler);
      return nextId;
    },
    clearTimeout: (id) => {
      pending.delete(id);
    },
  };
  const { createProbeTimer } = await contract();
  const timer = createProbeTimer(clock);
  const ran = [];

  // When failures reschedule again and again, then the tab hides and shows.
  timer.schedule(1_000, () => ran.push('first'));
  timer.schedule(2_000, () => ran.push('second'));
  timer.schedule(4_000, () => ran.push('third'));
  assert.equal(pending.size, 1, 'only the latest probe waits');
  timer.cancel();
  assert.equal(pending.size, 0, 'hiding the tab leaves no pending probe');
  timer.schedule(0, () => ran.push('shown'));
  timer.schedule(5_000, () => ran.push('manual'));
  assert.equal(pending.size, 1, 'a manual retry replaces the pending probe');

  // Then every superseded probe is gone and only the latest task can run.
  assert.deepEqual(ran, []);
  timer.schedule(1_000, () => ran.push('fired'));
  assert.equal(pending.size, 1);
  for (const [, handler] of [...pending]) handler();
  pending.clear();
  assert.deepEqual(ran, ['fired'], 'the surviving probe still fires its own task');
  timer.cancel();
  assert.equal(pending.size, 0);
});
