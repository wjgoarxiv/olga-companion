import { spawn } from 'node:child_process';
import { createConnection, createServer } from 'node:net';

const scheduler = {
  setTimer: (callback, delayMs) => setTimeout(callback, delayMs),
  clearTimer: (timer) => clearTimeout(timer),
};

export async function fetchWithDeadline(
  fetchImpl, url, init = {}, timeoutMs = 2_000, timers = scheduler,
) {
  const controller = new AbortController();
  const timeout = new Error('Readiness request timed out');
  const timer = timers.setTimer(() => controller.abort(timeout), timeoutMs);
  try {
    return await fetchImpl(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) throw timeout;
    throw error;
  } finally {
    timers.clearTimer(timer);
  }
}

export function canBindPort({ host, port }) {
  return new Promise((resolve) => {
    const server = createServer();
    server.unref();
    server.once('error', () => resolve(false));
    server.listen({ host, port, exclusive: true }, () => {
      server.close(() => resolve(true));
    });
  });
}

export async function assertPortsAvailable(config, checker = canBindPort) {
  if (!await checker({ host: config.frontendHost, port: config.frontendPort })) {
    throw new Error(`Frontend port ${config.frontendPort} is already in use`);
  }
  if (!await checker({ host: config.sidecarHost, port: config.sidecarPort })) {
    throw new Error(`Sidecar port ${config.sidecarPort} is already in use`);
  }
}

export function isPortListening(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const socket = createConnection({ host, port });
    const finish = (listening) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(listening);
    };
    socket.setTimeout(250, () => finish(false));
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
  });
}

function waitForCommand(command, args) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: 'ignore' });
    child.once('error', () => resolve());
    child.once('exit', () => resolve());
  });
}

export async function terminateProcessTree(child, signal) {
  if (!child?.pid) return;
  if (process.platform === 'win32') {
    const args = ['/pid', String(child.pid), '/t'];
    if (signal === 'SIGKILL') args.push('/f');
    await waitForCommand('taskkill', args);
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if (error?.code !== 'ESRCH') {
      try { child.kill?.(signal); } catch { /* process already exited */ }
    }
  }
}

export function waitForChildExit(child, graceMs) {
  if (!child?.pid || child.exitCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timer = setTimeout(() => finish(false), graceMs);
    const finish = (exited) => {
      clearTimeout(timer);
      child.removeListener?.('exit', onExit);
      resolve(exited);
    };
    const onExit = () => finish(true);
    child.once?.('exit', onExit);
    if (child.exitCode !== null) finish(true);
  });
}

export function processGroupAlive(child) {
  if (!child?.pid || process.platform === 'win32') return Promise.resolve(false);
  try {
    process.kill(-child.pid, 0);
    return Promise.resolve(true);
  } catch {
    return Promise.resolve(false);
  }
}

export async function waitForDescendantsExit(child, graceMs) {
  const deadline = Date.now() + graceMs;
  while (Date.now() < deadline) {
    if (!await processGroupAlive(child)) return true;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return !await processGroupAlive(child);
}

const cleanupDefaults = {
  terminate: terminateProcessTree,
  waitForExit: waitForChildExit,
  isPortListening,
  hasDescendants: processGroupAlive,
  waitForDescendants: waitForDescendantsExit,
  emitReceipt: () => {},
};

export async function cleanupOwnedRuntime(
  children, config, injected = {}, graceMs = 1_000,
) {
  const deps = { ...cleanupDefaults, ...injected };
  const owned = children.filter((child) => child?.pid);
  for (const child of owned) await deps.terminate(child, 'SIGTERM');
  const descendants = new Set();
  for (const child of owned) {
    if (!await deps.waitForExit(child, graceMs)) {
      await deps.terminate(child, 'SIGKILL');
      if (!await deps.waitForExit(child, graceMs)) descendants.add(child.name);
    }
    if (await deps.hasDescendants(child)) {
      await deps.terminate(child, 'SIGKILL');
      if (!await deps.waitForDescendants(child, graceMs)) descendants.add(child.name);
    }
  }
  const listeners = [];
  for (const port of [config.frontendPort, config.sidecarPort]) {
    if (await deps.isPortListening(port)) listeners.push(port);
  }
  const result = {
    cleanupComplete: listeners.length === 0 && descendants.size === 0,
    listeners,
    descendants: [...descendants],
  };
  await deps.emitReceipt({ event: 'CLEANUP', ...result });
  return result;
}
