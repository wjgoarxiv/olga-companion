#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import {
  assertHealthIdentity,
  assertSupportedNodeRuntime,
  buildSpawnSpecs,
  buildSupervisorReceipt,
  createSupervisorState,
  parseDevAppArgs,
  runReadinessChecks,
  transitionSupervisor,
} from './dev-app-contract.mjs';
import {
  assertPortsAvailable,
  cleanupOwnedRuntime,
  fetchWithDeadline,
} from './dev-app-io.mjs';

export {
  assertHealthIdentity,
  assertPortsAvailable,
  assertSupportedNodeRuntime,
  buildSpawnSpecs,
  buildSupervisorReceipt,
  cleanupOwnedRuntime,
  createSupervisorState,
  fetchWithDeadline,
  parseDevAppArgs,
  runReadinessChecks,
  transitionSupervisor,
};

const START_TIMEOUT_MS = 30_000;
const REQUEST_TIMEOUT_MS = 2_000;
const STABLE_INTERVAL_MS = 30_000;

function spawnQuiet(spec) {
  const child = spawn(spec.command, spec.args, {
    env: spec.env,
    stdio: 'ignore',
    detached: process.platform !== 'win32',
  });
  return Object.assign(child, { name: spec.name });
}

async function waitForOk(url, options, alive, boundedFetch) {
  const deadline = Date.now() + START_TIMEOUT_MS;
  let lastStatus = 'unreachable';
  while (Date.now() < deadline) {
    if (!alive()) throw new Error('Owned process exited during readiness');
    try {
      const response = await boundedFetch(
        fetch, url, { ...options, cache: 'no-store' }, REQUEST_TIMEOUT_MS,
      );
      lastStatus = String(response.status);
      if (response.ok) return response;
    } catch (error) {
      if (!alive()) throw new Error('Owned process exited during readiness');
      lastStatus = error?.message === 'Readiness request timed out' ? 'timed-out' : 'unreachable';
    }
    await delay(200);
  }
  throw new Error(`Readiness timed out (${lastStatus})`);
}

export async function runSupervisor(config) {
  const specs = buildSpawnSpecs(config);
  const expectedRuntime = {
    app: 'OLGA Companion',
    frontendPort: config.frontendPort,
    sidecarPort: config.sidecarPort,
  };
  let state = createSupervisorState();
  let sidecar = null;
  let frontend = null;
  let stopping = false;
  let requestedExitCode = 0;
  let cleanupPromise = null;
  let failedEmitted = false;
  let finishSupervisor;
  const supervisorDone = new Promise((resolve) => { finishSupervisor = resolve; });
  const emit = (event, receiptState = state, cleanupComplete = false) => {
    console.log(JSON.stringify(buildSupervisorReceipt(event, receiptState, config, {
      supervisorPid: process.pid,
      cleanupComplete,
    })));
  };
  const cleanup = async (exitCode) => {
    requestedExitCode = Math.max(requestedExitCode, exitCode);
    stopping = true;
    if (!cleanupPromise) {
      const stoppedState = {
        ...state, phase: 'stopped', ready: false, frontendPid: null, sidecarPid: null,
      };
      cleanupPromise = (async () => await cleanupOwnedRuntime(
        [frontend, sidecar], config,
        { emitReceipt: (result) => emit('CLEANUP', stoppedState, result.cleanupComplete) },
      ))();
    }
    const result = await cleanupPromise;
    state = { ...state, phase: 'stopped', ready: false, frontendPid: null, sidecarPid: null };
    frontend = null;
    sidecar = null;
    process.exitCode = result.cleanupComplete ? requestedExitCode : 1;
    finishSupervisor();
    return result;
  };
  const failClosed = async () => {
    if (!failedEmitted) {
      state = { ...state, phase: 'failed', ready: false };
      emit('FAILED');
      failedEmitted = true;
    }
    await cleanup(1);
  };
  const dispatch = async (event) => {
    const transition = transitionSupervisor(state, event);
    state = transition.state;
    const exit = transition.effects.find((effect) => effect.type === 'EXIT');
    if (exit) requestedExitCode = Math.max(requestedExitCode, exit.code);
    for (const effect of transition.effects) await enact(effect);
  };
  const observeExit = (child, type) => {
    let reported = false;
    const report = (code) => {
      if (reported) return;
      reported = true;
      if (!stopping) void dispatch({ type, code }).catch(failClosed);
    };
    child.once('error', () => report(1));
    child.once('exit', report);
  };
  const requestOk = (url, options, alive) => waitForOk(
    url, options, alive, fetchWithDeadline,
  );
  const spawnSidecar = async () => {
    const child = spawnQuiet(specs.sidecar);
    sidecar = child;
    await once(child, 'spawn');
    if (stopping) return;
    observeExit(child, 'SIDECAR_EXITED');
    await dispatch({ type: 'SIDECAR_SPAWNED', pid: child.pid });
    const directHealth = await requestOk(
      `http://${config.sidecarHost}:${config.sidecarPort}/health`, {},
      () => !stopping && sidecar?.exitCode === null,
    );
    assertHealthIdentity(await directHealth.json(), expectedRuntime);
    await dispatch({ type: 'SIDECAR_DIRECT_READY' });
  };
  const spawnFrontend = async () => {
    const child = spawnQuiet(specs.vite);
    frontend = child;
    await once(child, 'spawn');
    if (stopping) return;
    observeExit(child, 'FRONTEND_EXITED');
    await dispatch({ type: 'FRONTEND_SPAWNED', pid: child.pid });
  };
  const childrenAlive = () => !stopping
    && sidecar?.exitCode === null
    && frontend?.exitCode === null;
  const verify = async () => {
    const origin = `http://${config.frontendHost}:${config.frontendPort}`;
    await runReadinessChecks({
      proxyHealth: async () => (await requestOk(`${origin}/health`, {}, childrenAlive)).json(),
      issueSessionToken: async () => {
        const response = await requestOk(`${origin}/api/session/token`, {}, childrenAlive);
        return {
          token: (await response.json()).token,
          cacheControl: response.headers.get('cache-control'),
        };
      },
      protectedRead: (token) => requestOk(`${origin}/api/workspace/context`, {
        headers: { 'x-session-token': token },
      }, childrenAlive),
      childrenAlive,
    }, expectedRuntime);
    await dispatch({ type: 'READINESS_VERIFIED' });
  };
  const enact = async (effect) => {
    if (effect.type === 'SPAWN_SIDECAR') await spawnSidecar();
    else if (effect.type === 'SPAWN_FRONTEND') await spawnFrontend();
    else if (effect.type === 'VERIFY_PROXY_CONTRACT') await verify();
    else if (effect.type === 'EMIT_RECEIPT') emit(effect.receipt);
    else if (effect.type === 'SCHEDULE_SIDECAR_RESTART') {
      await delay(effect.delayMs);
      if (!stopping) await spawnSidecar();
    } else if (effect.type === 'SCHEDULE_STABILITY_RESET') {
      void delay(STABLE_INTERVAL_MS, undefined, { ref: false })
        .then(() => dispatch({ type: 'STABLE_INTERVAL_ELAPSED' })).catch(failClosed);
    } else if (effect.type === 'TERMINATE_OWNED_PAIR') {
      await cleanup(requestedExitCode);
    } else if (effect.type === 'EXIT') process.exitCode = requestedExitCode;
  };
  const handleSignal = (signal) => {
    void dispatch({ type: 'SIGNAL', signal }).catch(failClosed);
  };
  process.once('SIGINT', handleSignal);
  process.once('SIGTERM', handleSignal);
  try {
    await assertPortsAvailable(config);
    if (stopping) {
      if (cleanupPromise) await cleanupPromise;
      return;
    }
    await dispatch({ type: 'START' });
    await supervisorDone;
  } catch (error) {
    if (!stopping) {
      await failClosed();
      throw error;
    }
    if (cleanupPromise) await cleanupPromise;
  } finally {
    process.removeListener('SIGINT', handleSignal);
    process.removeListener('SIGTERM', handleSignal);
  }
}

async function main() {
  try {
    assertSupportedNodeRuntime();
  } catch {
    console.error(JSON.stringify({ event: 'FAILED', reason: 'unsupported_node_runtime' }));
    process.exitCode = 1;
    return;
  }
  let config;
  try {
    config = parseDevAppArgs(process.argv.slice(2));
  } catch {
    console.error(JSON.stringify({ event: 'FAILED', reason: 'invalid_configuration' }));
    process.exitCode = 1;
    return;
  }
  await runSupervisor(config).catch(() => {
    process.exitCode = 1;
  });
}

const invokedPath = process.argv[1] ? fileURLToPath(import.meta.url) === process.argv[1] : false;
if (invokedPath) void main();
