import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const runtimeModule = import('../../scripts/dev-app.mjs');
const source = await readFile(new URL('../../scripts/dev-app.mjs', import.meta.url), 'utf8');

const config = Object.freeze({
  frontendHost: '127.0.0.1',
  frontendPort: 5274,
  sidecarHost: '127.0.0.1',
  sidecarPort: 8866,
});

const expectedRuntime = Object.freeze({
  app: 'OLGA Companion',
  frontendPort: 5274,
  sidecarPort: 8866,
});

function health(overrides = {}) {
  return {
    app: 'OLGA Companion',
    frontend_port: 5274,
    sidecar_port: 8866,
    ...overrides,
  };
}

function readinessProbes(overrides = {}) {
  return {
    proxyHealth: async () => health(),
    issueSessionToken: async () => ({ token: 'opaque-secret', cacheControl: 'no-store' }),
    protectedRead: async (token) => assert.equal(token, 'opaque-secret'),
    childrenAlive: () => true,
    ...overrides,
  };
}

test('rejects an occupied frontend port before the sidecar spawn transition', async () => {
  // Given: the frontend listener is already owned by another process.
  const { assertPortsAvailable } = await runtimeModule;
  const checked = [];

  // When/Then: preflight rejects at the first occupied port without checking later ports.
  await assert.rejects(
    assertPortsAvailable(config, async ({ port }) => {
      checked.push(port);
      return port !== 5274;
    }),
    { message: 'Frontend port 5274 is already in use' },
  );
  assert.deepEqual(checked, [5274]);
});

test('rejects an occupied sidecar port after confirming the frontend port is free', async () => {
  // Given: only the requested sidecar port is occupied.
  const { assertPortsAvailable } = await runtimeModule;
  const checked = [];

  // When/Then: both loopback ports are checked and the sidecar conflict is explicit.
  await assert.rejects(
    assertPortsAvailable(config, async ({ port }) => {
      checked.push(port);
      return port !== 8866;
    }),
    { message: 'Sidecar port 8866 is already in use' },
  );
  assert.deepEqual(checked, [5274, 8866]);
});

test('wires port preflight before the transition that can spawn a child', () => {
  // Given: the canonical supervisor source.
  const runSupervisor = source.slice(source.indexOf('export async function runSupervisor'));

  // When: startup orchestration is inspected.
  const preflightIndex = runSupervisor.indexOf('await assertPortsAvailable(');
  const startIndex = runSupervisor.indexOf("await dispatch({ type: 'START' })");

  // Then: fail-fast preflight is present and precedes the first spawn-capable transition.
  assert.notEqual(preflightIndex, -1);
  assert.notEqual(startIndex, -1);
  assert.ok(preflightIndex < startIndex);
});

test('accepts readiness only for the expected app, ports, and no-store token response', async () => {
  // Given: authenticated readiness probes matching the requested runtime pair.
  const { runReadinessChecks } = await runtimeModule;

  // When: the complete readiness contract is verified.
  const result = await runReadinessChecks(readinessProbes(), expectedRuntime);

  // Then: a bounded, secret-free READY result is returned.
  assert.deepEqual(result, { status: 'ready' });
  assert.doesNotMatch(JSON.stringify(result), /opaque-secret/);
});

test('rejects a health payload whose app or ports do not match the owned runtime', async () => {
  // Given: misleading healthy payloads from an unexpected app and sidecar port.
  const { runReadinessChecks } = await runtimeModule;
  const payloads = [health({ app: 'Foreign service' }), health({ sidecar_port: 9999 })];

  // When/Then: neither payload can produce READY.
  for (const payload of payloads) {
    await assert.rejects(
      runReadinessChecks(readinessProbes({
        proxyHealth: async () => payload,
        protectedRead: async () => {},
      }), expectedRuntime),
      { message: 'Runtime health identity mismatch' },
    );
  }
});

test('rejects a token response that is cacheable', async () => {
  // Given: a syntactically valid token delivered without the required no-store policy.
  const { runReadinessChecks } = await runtimeModule;
  const probes = readinessProbes({
    issueSessionToken: async () => ({ token: 'opaque-secret', cacheControl: 'max-age=60' }),
    protectedRead: async () => {},
  });

  // When/Then: cacheable credentials block READY.
  await assert.rejects(
    runReadinessChecks(probes, expectedRuntime),
    { message: 'Session token response must be no-store' },
  );
});

test('aborts a hung fetch through one injected bounded deadline', async () => {
  // Given: a fetch that settles only when its signal is aborted.
  const { fetchWithDeadline } = await runtimeModule;
  const observed = { delayMs: null, signal: null, cleared: false };
  const fetchImpl = (_url, init) => new Promise((_resolve, reject) => {
    observed.signal = init.signal;
    init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true });
  });
  const scheduler = {
    setTimer: (callback, delayMs) => {
      observed.delayMs = delayMs;
      queueMicrotask(callback);
      return 91;
    },
    clearTimer: (timerId) => {
      assert.equal(timerId, 91);
      observed.cleared = true;
    },
  };

  // When/Then: the request receives AbortSignal and rejects without real time or a leaked timer.
  await assert.rejects(
    fetchWithDeadline(fetchImpl, 'http://127.0.0.1:5274/health', {}, 2_000, scheduler),
    { message: 'Readiness request timed out' },
  );
  assert.ok(observed.signal instanceof AbortSignal);
  assert.equal(observed.signal.aborted, true);
  assert.equal(observed.delayMs, 2_000);
  assert.equal(observed.cleared, true);
});

test('builds truthful degraded and cleanup receipts without retaining a dead sidecar PID', async () => {
  // Given: degraded state after the one allowed sidecar restart begins.
  const { buildSupervisorReceipt } = await runtimeModule;
  const degraded = {
    phase: 'degraded', ready: false, restartAttempts: 1,
    frontendPid: 8102, sidecarPid: null,
  };

  // When: operator receipts are built before and after verified cleanup.
  const receipt = buildSupervisorReceipt('DEGRADED', degraded, config, {
    supervisorPid: 8100,
    cleanupComplete: false,
  });
  const cleanup = buildSupervisorReceipt('CLEANUP', {
    ...degraded, phase: 'stopped', frontendPid: null,
  }, config, { supervisorPid: 8100, cleanupComplete: true });

  // Then: ownership, liveness, retries, ports, and cleanup truth are explicit.
  assert.deepEqual(receipt, {
    event: 'DEGRADED', supervisorPid: 8100, phase: 'degraded', ready: false,
    restartAttempts: 1, frontendPid: 8102, sidecarPid: null,
    frontendPort: 5274, sidecarPort: 8866, cleanupComplete: false,
  });
  assert.equal(cleanup.event, 'CLEANUP');
  assert.equal(cleanup.phase, 'stopped');
  assert.equal(cleanup.frontendPid, null);
  assert.equal(cleanup.sidecarPid, null);
  assert.equal(cleanup.cleanupComplete, true);
});

test('waits, escalates a stubborn child, verifies listeners, then emits cleanup', async () => {
  // Given: one graceful child and one child that requires escalation.
  const { cleanupOwnedRuntime } = await runtimeModule;
  const operations = [];
  const waits = new Map();
  const children = [
    { name: 'frontend', pid: 9101 },
    { name: 'sidecar', pid: 9102 },
  ];
  const dependencies = {
    terminate: async (child, signal) => { operations.push(`terminate:${child.name}:${signal}`); },
    waitForExit: async (child, graceMs) => {
      operations.push(`wait:${child.name}:${graceMs}`);
      const attempt = (waits.get(child.name) ?? 0) + 1;
      waits.set(child.name, attempt);
      return child.name === 'frontend' || attempt > 1;
    },
    isPortListening: async (port) => {
      operations.push(`listen:${port}`);
      return false;
    },
    emitReceipt: (receipt) => { operations.push(`receipt:${receipt.event}`); },
  };

  // When: owned runtime cleanup runs with an injected bounded grace interval.
  const result = await cleanupOwnedRuntime(children, config, dependencies, 750);

  // Then: TERM is awaited, the stubborn child gets KILL, ports are clear, and receipt is last.
  assert.deepEqual(result, { cleanupComplete: true, listeners: [], descendants: [] });
  assert.ok(operations.includes('terminate:frontend:SIGTERM'));
  assert.ok(operations.includes('terminate:sidecar:SIGTERM'));
  assert.ok(operations.includes('terminate:sidecar:SIGKILL'));
  assert.equal(waits.get('frontend'), 1);
  assert.equal(waits.get('sidecar'), 2);
  assert.ok(operations.indexOf('listen:5274') < operations.indexOf('receipt:CLEANUP'));
  assert.ok(operations.indexOf('listen:8866') < operations.indexOf('receipt:CLEANUP'));
  assert.equal(operations.at(-1), 'receipt:CLEANUP');
});

test('wires bounded fetch and awaited cleanup into the live supervisor', () => {
  // Given: the canonical supervisor source after its exported helpers.
  const runSupervisor = source.slice(source.indexOf('export async function runSupervisor'));

  // When/Then: live orchestration uses the hardened fetch and cleanup paths.
  assert.match(runSupervisor, /fetchWithDeadline/);
  assert.match(runSupervisor, /await cleanupOwnedRuntime/);
});
