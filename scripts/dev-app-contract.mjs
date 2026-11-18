const LOOPBACK = '127.0.0.1';

function parsePort(value, label) {
  if (!/^\d+$/.test(value ?? '')) throw new Error(`Invalid ${label} port`);
  const port = Number(value);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`Invalid ${label} port`);
  }
  return port;
}

export function parseDevAppArgs(args) {
  const config = {
    frontendHost: LOOPBACK,
    frontendPort: 5273,
    sidecarHost: LOOPBACK,
    sidecarPort: 8865,
  };
  for (let index = 0; index < args.length; index += 2) {
    const option = args[index];
    const value = args[index + 1];
    if (option === '--frontend-port') config.frontendPort = parsePort(value, 'frontend');
    else if (option === '--sidecar-port') config.sidecarPort = parsePort(value, 'sidecar');
    else throw new Error(`Unknown or invalid option: ${option ?? '(missing)'}`);
  }
  if (config.frontendPort === config.sidecarPort) throw new Error('Ports must be distinct');
  return config;
}

export function assertSupportedNodeRuntime(version = process.versions.node) {
  const [major, minor] = version.split('.').map(Number);
  const supported = (major === 20 && minor >= 19)
    || (major === 22 && minor >= 12)
    || major >= 23;
  if (!supported) throw new Error('Unsupported Node runtime');
}

export function buildSpawnSpecs(config) {
  const sidecarOrigin = `http://${config.sidecarHost}:${config.sidecarPort}`;
  return {
    sidecar: {
      name: 'sidecar',
      command: 'uv',
      args: [
        'run', '--extra', 'results', 'python', '-m', 'olga_companion.sidecar',
        '--host', config.sidecarHost, '--port', String(config.sidecarPort),
        '--frontend-port', String(config.frontendPort),
      ],
      env: { ...process.env, PYTHONPATH: 'src' },
    },
    vite: {
      name: 'frontend',
      command: process.execPath,
      args: [
        'node_modules/vite/bin/vite.js', '--config', 'frontend/vite.config.ts',
        '--host', config.frontendHost, '--port', String(config.frontendPort), '--strictPort',
      ],
      env: {
        ...process.env,
        OLGA_SIDECAR_ORIGIN: sidecarOrigin,
        OLGA_PROXY_ORIGIN: sidecarOrigin,
      },
    },
  };
}

export function assertHealthIdentity(payload, expected) {
  if (
    payload?.app !== expected.app
    || payload?.frontend_port !== expected.frontendPort
    || payload?.sidecar_port !== expected.sidecarPort
  ) throw new Error('Runtime health identity mismatch');
}

export async function runReadinessChecks(probes, expectedRuntime) {
  if (!probes.childrenAlive()) throw new Error('Owned process exited during readiness');
  const health = await probes.proxyHealth();
  if (expectedRuntime) assertHealthIdentity(health, expectedRuntime);
  const credential = await probes.issueSessionToken();
  if (expectedRuntime && credential?.cacheControl?.toLowerCase() !== 'no-store') {
    throw new Error('Session token response must be no-store');
  }
  const token = typeof credential === 'string' ? credential : credential?.token;
  if (typeof token !== 'string' || !token || token.length > 4_096) {
    throw new Error('Invalid session token response');
  }
  await probes.protectedRead(token);
  if (!probes.childrenAlive()) throw new Error('Owned process exited during readiness');
  return { status: 'ready' };
}

export function createSupervisorState() {
  return {
    phase: 'idle', ready: false, sidecarPid: null, frontendPid: null, restartAttempts: 0,
  };
}

export function buildSupervisorReceipt(event, state, config, runtime) {
  return {
    event,
    supervisorPid: runtime.supervisorPid,
    phase: state.phase,
    ready: state.ready,
    restartAttempts: state.restartAttempts,
    frontendPid: state.frontendPid ?? null,
    sidecarPid: state.sidecarPid ?? null,
    frontendPort: config.frontendPort,
    sidecarPort: config.sidecarPort,
    cleanupComplete: runtime.cleanupComplete,
  };
}

export function transitionSupervisor(state, event) {
  const next = { ...state };
  const effects = [];
  if (event.type === 'START') {
    next.phase = 'starting-sidecar';
    effects.push({ type: 'SPAWN_SIDECAR' });
  } else if (event.type === 'SIDECAR_SPAWNED') {
    next.sidecarPid = event.pid;
  } else if (event.type === 'SIDECAR_DIRECT_READY') {
    if (next.frontendPid === null) {
      next.phase = 'starting-frontend';
      effects.push({ type: 'SPAWN_FRONTEND' });
    } else {
      next.phase = 'verifying';
      effects.push({ type: 'VERIFY_PROXY_CONTRACT' });
    }
  } else if (event.type === 'FRONTEND_SPAWNED') {
    next.frontendPid = event.pid;
    next.phase = 'verifying';
    effects.push({ type: 'VERIFY_PROXY_CONTRACT' });
  } else if (event.type === 'READINESS_VERIFIED') {
    next.phase = 'ready';
    next.ready = true;
    effects.push({ type: 'EMIT_RECEIPT', receipt: 'READY' });
    if (next.restartAttempts > 0) effects.push({ type: 'SCHEDULE_STABILITY_RESET' });
  } else if (event.type === 'STABLE_INTERVAL_ELAPSED') {
    next.restartAttempts = 0;
  } else if (event.type === 'SIDECAR_EXITED') {
    next.sidecarPid = null;
    next.ready = false;
    if (next.restartAttempts === 0 && next.frontendPid !== null) {
      next.phase = 'degraded';
      next.restartAttempts = 1;
      effects.push(
        { type: 'EMIT_RECEIPT', receipt: 'DEGRADED' },
        { type: 'SCHEDULE_SIDECAR_RESTART', delayMs: 500 },
      );
    } else {
      next.phase = 'failed';
      effects.push(
        { type: 'EMIT_RECEIPT', receipt: 'FAILED' },
        { type: 'TERMINATE_OWNED_PAIR' }, { type: 'EXIT', code: 1 },
      );
    }
  } else if (event.type === 'FRONTEND_EXITED') {
    next.frontendPid = null;
    next.ready = false;
    next.phase = 'failed';
    effects.push(
      { type: 'EMIT_RECEIPT', receipt: 'FAILED' },
      { type: 'TERMINATE_OWNED_PAIR' }, { type: 'EXIT', code: 1 },
    );
  } else if (event.type === 'SIGNAL') {
    next.ready = false;
    next.phase = 'stopping';
    effects.push({ type: 'TERMINATE_OWNED_PAIR' }, { type: 'EXIT', code: 0 });
  }
  return { state: next, effects };
}
