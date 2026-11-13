import assert from 'node:assert/strict';
import test from 'node:test';

const runtimeModule = import('../../scripts/dev-app.mjs');

async function runtime() {
  return runtimeModule;
}

function hasEffect(transition, type) {
  return transition.effects.find((effect) => effect.type === type);
}

function advance(transitionSupervisor, transition, event) {
  return transitionSupervisor(transition.state, event);
}

test('uses the existing diagnostic ports when no overrides are supplied', async () => {
  // Given: an empty canonical supervisor CLI.
  const { parseDevAppArgs } = await runtime();

  // When: defaults are parsed.
  const config = parseDevAppArgs([]);

  // Then: the established Vite and sidecar ports remain unchanged.
  assert.equal(config.frontendPort, 5273);
  assert.equal(config.sidecarPort, 8865);
});

test('parses only distinct loopback integer port options', async () => {
  // Given: the canonical isolated-QA port arguments.
  const { parseDevAppArgs } = await runtime();

  // When: the supervisor parses its public CLI boundary.
  const config = parseDevAppArgs(['--frontend-port', '5274', '--sidecar-port', '8866']);

  // Then: both services are pinned to loopback with distinct integer ports.
  assert.deepEqual(config, {
    frontendHost: '127.0.0.1',
    frontendPort: 5274,
    sidecarHost: '127.0.0.1',
    sidecarPort: 8866,
  });
});

test('rejects malformed, out-of-range, equal, and host override arguments', async () => {
  // Given: untrusted CLI argument sets that could escape loopback or collide.
  const { parseDevAppArgs } = await runtime();
  const invalidArgs = [
    ['--frontend-port', '5274.5'],
    ['--sidecar-port', 'not-a-port'],
    ['--frontend-port', '0'],
    ['--sidecar-port', '65536'],
    ['--frontend-port', '5274', '--sidecar-port', '5274'],
    ['--frontend-host', '0.0.0.0'],
    ['--sidecar-host', '192.168.0.10'],
  ];

  // When/Then: every invalid boundary is rejected with bounded public copy.
  for (const args of invalidArgs) {
    assert.throws(
      () => parseDevAppArgs(args),
      (error) => error instanceof Error && /invalid|unknown|distinct|port/i.test(error.message),
      args.join(' '),
    );
  }
});

test('propagates one validated port pair into both child spawn specifications', async () => {
  // Given: one validated custom-port configuration.
  const { buildSpawnSpecs, parseDevAppArgs } = await runtime();
  const config = parseDevAppArgs(['--frontend-port', '5274', '--sidecar-port', '8866']);

  // When: child process specifications are derived.
  const specs = buildSpawnSpecs(config);

  // Then: Vite, its proxy environment, and the sidecar receive the same values.
  assert.deepEqual(specs.vite.args.slice(-5), ['--host', '127.0.0.1', '--port', '5274', '--strictPort']);
  assert.equal(specs.vite.env.OLGA_SIDECAR_ORIGIN, 'http://127.0.0.1:8866');
  assert.equal(specs.vite.env.OLGA_PROXY_ORIGIN, 'http://127.0.0.1:8866');
  assert.deepEqual(
    specs.sidecar.args.slice(-6),
    ['--host', '127.0.0.1', '--port', '8866', '--frontend-port', '5274'],
  );
});

test('checks proxied health, token issuance, and protected read before readiness', async () => {
  // Given: observable, dependency-injected readiness probes.
  const { runReadinessChecks } = await runtime();
  const calls = [];
  let aliveChecks = 0;

  // When: the authenticated proxy contract is checked.
  const result = await runReadinessChecks({
    proxyHealth: async () => { calls.push('proxy-health'); },
    issueSessionToken: async () => {
      calls.push('session-token');
      return 'opaque-secret';
    },
    protectedRead: async (token) => {
      assert.equal(token, 'opaque-secret');
      calls.push('protected-read');
    },
    childrenAlive: () => {
      aliveChecks += 1;
      return true;
    },
  });

  // Then: child ownership brackets deterministic checks and the secret stays out of the receipt.
  assert.deepEqual(calls, ['proxy-health', 'session-token', 'protected-read']);
  assert.equal(aliveChecks, 2);
  assert.deepEqual(result, { status: 'ready' });
  assert.doesNotMatch(JSON.stringify(result), /opaque-secret/);
});

test('blocks READY when an owned child exits during readiness verification', async () => {
  // Given: probes succeed, but the child-liveness guard flips before completion.
  const { runReadinessChecks } = await runtime();
  const calls = [];
  let aliveChecks = 0;
  const probes = {
    proxyHealth: async () => { calls.push('proxy-health'); },
    issueSessionToken: async () => {
      calls.push('session-token');
      return 'opaque-secret';
    },
    protectedRead: async () => { calls.push('protected-read'); },
    childrenAlive: () => {
      aliveChecks += 1;
      calls.push(`children-alive-${aliveChecks}`);
      return aliveChecks === 1;
    },
  };

  // When/Then: verification rejects immediately after its bounded second liveness check.
  await assert.rejects(
    runReadinessChecks(probes),
    { message: 'Owned process exited during readiness' },
  );
  assert.deepEqual(calls, [
    'children-alive-1',
    'proxy-health',
    'session-token',
    'protected-read',
    'children-alive-2',
  ]);
  assert.equal(aliveChecks, 2);
});

test('starts Vite only after direct sidecar health and emits READY after verification', async () => {
  // Given: a fresh supervisor state machine.
  const module = await runtime();
  const { transitionSupervisor } = module;
  let transition = { state: module.createSupervisorState(), effects: [] };

  // When: startup evidence arrives in its required order.
  transition = advance(transitionSupervisor, transition, { type: 'START' });
  assert.ok(hasEffect(transition, 'SPAWN_SIDECAR'));
  transition = advance(transitionSupervisor, transition, { type: 'SIDECAR_SPAWNED', pid: 4101 });
  assert.equal(hasEffect(transition, 'SPAWN_FRONTEND'), undefined);
  transition = advance(transitionSupervisor, transition, { type: 'SIDECAR_DIRECT_READY' });
  assert.ok(hasEffect(transition, 'SPAWN_FRONTEND'));
  transition = advance(transitionSupervisor, transition, { type: 'FRONTEND_SPAWNED', pid: 4102 });
  assert.ok(hasEffect(transition, 'VERIFY_PROXY_CONTRACT'));
  transition = advance(transitionSupervisor, transition, { type: 'READINESS_VERIFIED' });

  // Then: READY is truthful and both owned children are retained.
  assert.equal(transition.state.phase, 'ready');
  assert.equal(transition.state.frontendPid, 4102);
  assert.equal(transition.state.sidecarPid, 4101);
  assert.deepEqual(hasEffect(transition, 'EMIT_RECEIPT'), { type: 'EMIT_RECEIPT', receipt: 'READY' });
});

test('first sidecar death invalidates READY, preserves Vite, and schedules one bounded restart', async () => {
  // Given: a ready supervisor with both child PIDs.
  const module = await runtime();
  const { transitionSupervisor } = module;
  const readyState = {
    ...module.createSupervisorState(),
    phase: 'ready',
    ready: true,
    sidecarPid: 5101,
    frontendPid: 5102,
  };

  // When: the first sidecar exits inside the unstable window.
  const transition = transitionSupervisor(readyState, { type: 'SIDECAR_EXITED', code: 1 });

  // Then: Vite remains owned while readiness is visibly invalidated and restart is bounded.
  assert.equal(transition.state.phase, 'degraded');
  assert.equal(transition.state.ready, false);
  assert.equal(transition.state.frontendPid, 5102);
  assert.equal(transition.state.sidecarPid, null);
  assert.deepEqual(hasEffect(transition, 'EMIT_RECEIPT'), { type: 'EMIT_RECEIPT', receipt: 'DEGRADED' });
  const restart = hasEffect(transition, 'SCHEDULE_SIDECAR_RESTART');
  assert.ok(restart);
  assert.ok(restart.delayMs > 0 && restart.delayMs <= 1_000);
  assert.equal(hasEffect(transition, 'TERMINATE_OWNED_PAIR'), undefined);
});

test('a repeated sidecar death in the unstable window cleans the pair and exits nonzero', async () => {
  // Given: the one allowed restart has already been consumed.
  const module = await runtime();
  const { transitionSupervisor } = module;
  const restartedState = {
    ...module.createSupervisorState(),
    phase: 'ready',
    ready: true,
    restartAttempts: 1,
    sidecarPid: 6101,
    frontendPid: 6102,
  };

  // When: the restarted sidecar exits again before stability is re-established.
  const transition = transitionSupervisor(restartedState, { type: 'SIDECAR_EXITED', code: 1 });

  // Then: the supervisor fails closed instead of starting a restart storm.
  assert.equal(transition.state.phase, 'failed');
  assert.equal(transition.state.ready, false);
  assert.ok(hasEffect(transition, 'TERMINATE_OWNED_PAIR'));
  assert.deepEqual(hasEffect(transition, 'EXIT'), { type: 'EXIT', code: 1 });
  assert.equal(hasEffect(transition, 'SCHEDULE_SIDECAR_RESTART'), undefined);
});

test('SIGINT and frontend exit invalidate READY and clean every owned child', async () => {
  // Given: a ready owned pair.
  const module = await runtime();
  const { transitionSupervisor } = module;
  const readyState = {
    ...module.createSupervisorState(),
    phase: 'ready',
    ready: true,
    sidecarPid: 7101,
    frontendPid: 7102,
  };

  // When: explicit shutdown or frontend death occurs.
  const signal = transitionSupervisor(readyState, { type: 'SIGNAL', signal: 'SIGINT' });
  const frontendExit = transitionSupervisor(readyState, { type: 'FRONTEND_EXITED', code: 1 });

  // Then: both paths invalidate readiness and terminate the complete owned pair.
  assert.equal(signal.state.ready, false);
  assert.ok(hasEffect(signal, 'TERMINATE_OWNED_PAIR'));
  assert.deepEqual(hasEffect(signal, 'EXIT'), { type: 'EXIT', code: 0 });
  assert.equal(frontendExit.state.ready, false);
  assert.ok(hasEffect(frontendExit, 'TERMINATE_OWNED_PAIR'));
  assert.deepEqual(hasEffect(frontendExit, 'EXIT'), { type: 'EXIT', code: 1 });
});
