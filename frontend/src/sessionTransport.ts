import type { Health, ProviderInfo } from './types';
import { jsonOrThrow } from './sessionResponse';

const PACKAGED_SIDECAR_ORIGIN = 'http://127.0.0.1:8865';

export type TransportFailureCode = 'local_runtime_offline' | 'local_session_expired';
export type TransportFailureState = 'offline' | 'reconnecting';

export class TransportFailure extends Error {
  readonly name = 'TransportFailure';
  readonly retryable = true;

  private constructor(
    readonly code: TransportFailureCode,
    readonly state: TransportFailureState,
    readonly operatorMessage: string,
  ) {
    super(operatorMessage);
  }

  static offline(): TransportFailure {
    return new TransportFailure('local_runtime_offline', 'offline', 'Local runtime is offline');
  }

  static expired(): TransportFailure {
    return new TransportFailure('local_session_expired', 'reconnecting', 'Local session expired');
  }
}

export function isTransportFailure(error: unknown): error is TransportFailure {
  return error instanceof TransportFailure;
}

type TransportFailureListener = (failure: TransportFailure) => void;
const failureListeners = new Set<TransportFailureListener>();

export function subscribeTransportFailures(listener: TransportFailureListener): () => void {
  failureListeners.add(listener);
  return () => failureListeners.delete(listener);
}

function publishFailure(failure: TransportFailure): void {
  for (const listener of failureListeners) {
    try {
      listener(failure);
    } catch {
      // A UI observer cannot change the outcome of the request it observes.
    }
  }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function resolveLocalInput(input: RequestInfo | URL): RequestInfo | URL {
  if (typeof input !== 'string' || !input.startsWith('/')) return input;
  const { location } = window;
  const packaged = location.hostname === 'tauri.localhost' || location.protocol === 'tauri:';
  return packaged ? new URL(input, PACKAGED_SIDECAR_ORIGIN) : input;
}

async function localFetch(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  try {
    return await fetch(resolveLocalInput(input), init);
  } catch (error: unknown) {
    if (isAbort(error)) throw error;
    const failure = TransportFailure.offline();
    publishFailure(failure);
    throw failure;
  }
}

// The per-boot token is rotated by safe hydration and read at request time.
let sessionToken = '';

export async function fetchSessionToken(): Promise<string> {
  const response = await localFetch('/api/session/token', { cache: 'no-store' });
  const body = (await jsonOrThrow(response)) as { token: string };
  sessionToken = body.token;
  return sessionToken;
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Session-Token', sessionToken);
  const response = await localFetch(input, { ...init, headers });
  if (response.status === 401) {
    const failure = TransportFailure.expired();
    publishFailure(failure);
    throw failure;
  }
  return response;
}

export async function fetchHealth(): Promise<Health> {
  return (await jsonOrThrow(await localFetch('/health', { cache: 'no-store' }))) as Health;
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const body = (await jsonOrThrow(await apiFetch('/api/providers'))) as { providers: ProviderInfo[] };
  return body.providers;
}
