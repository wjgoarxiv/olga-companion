import { useEffect, useRef, useState } from 'react';
import {
  createInitialSessionIntent,
  createProbeTimer,
  createRuntimeCommitGate,
  createRuntimeRecovery,
  offlineProbeDelayMs,
  shouldScheduleRuntimeProbe,
  type RuntimeState,
} from './runtimeLifecycle';
import * as session from './session';
import { subscribeTransportFailures, type TransportFailureCode } from './sessionTransport';
import type { Health, ProviderInfo } from './types';

const PROBE_DELAY_MS = 20_000;
const MAX_RECOVERY_ATTEMPTS = 4;

type OperatorMessage =
  | ''
  | 'Connecting to local runtime'
  | 'Local runtime is offline'
  | 'Local session expired'
  | 'Local runtime is unavailable';

interface UseRuntimeConnectionArgs {
  readonly sessionId: string;
  readonly startInitialSession: () => Promise<void>;
  readonly onProviders: (providers: ProviderInfo[]) => void;
  readonly onWorkspace: (workspace: session.WorkspaceContext) => void;
}

function transportMessage(code: TransportFailureCode): OperatorMessage {
  return code === 'local_session_expired' ? 'Local session expired' : 'Local runtime is offline';
}

export function useRuntimeConnection(args: UseRuntimeConnectionArgs) {
  const [health, setHealth] = useState<Health | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [state, setState] = useState<RuntimeState>('connecting');
  const [operatorMessage, setOperatorMessage] = useState<OperatorMessage>('Connecting to local runtime');
  const [busy, setBusy] = useState(false);
  const argsRef = useRef(args);
  const stateRef = useRef<RuntimeState>('connecting');
  const activeRef = useRef(true);
  const generationRef = useRef(0);
  const probeTimerRef = useRef(createProbeTimer());
  const attemptsRef = useRef(0);
  const activeRunRef = useRef<Promise<void> | null>(null);
  const commitGateRef = useRef(createRuntimeCommitGate());
  const initialSessionIntentRef = useRef(createInitialSessionIntent());
  argsRef.current = args;

  function transition(next: RuntimeState): void {
    stateRef.current = next;
    setState(next);
  }

  function createRecovery() {
    return createRuntimeRecovery<Health, string, ProviderInfo[], session.WorkspaceContext>({
      operations: {
        health: session.fetchHealth,
        token: session.fetchSessionToken,
        providers: session.fetchProviders,
        workspace: session.fetchWorkspaceContext,
      },
    });
  }

  const recoveryRef = useRef<ReturnType<typeof createRecovery> | null>(null);

  function getRecovery(): ReturnType<typeof createRecovery> {
    const current = recoveryRef.current;
    if (current) return current;
    const next = createRecovery();
    recoveryRef.current = next;
    return next;
  }

  function clearTimer(): void {
    probeTimerRef.current.cancel();
  }

  function schedule(delayMs: number): void {
    probeTimerRef.current.cancel();
    if (!shouldScheduleRuntimeProbe({ visibility: document.visibilityState, state: stateRef.current })) return;
    probeTimerRef.current.schedule(delayMs, () => {
      void runRecovery();
    });
  }

  function failRecovery(message: OperatorMessage = 'Local runtime is unavailable'): void {
    setHealth(null);
    attemptsRef.current += 1;
    if (attemptsRef.current >= MAX_RECOVERY_ATTEMPTS) {
      transition('offline');
      setOperatorMessage('Local runtime is offline');
    } else {
      transition('reconnecting');
      setOperatorMessage(message);
    }
    // Offline keeps probing with the bounded backoff; only the manual retry
    // resets the attempt count.
    schedule(offlineProbeDelayMs(attemptsRef.current));
  }

  async function performRecovery(): Promise<void> {
    const generation = generationRef.current;
    const commitRequest = commitGateRef.current.begin();
    setBusy(true);
    let result;
    try {
      result = await getRecovery().retry();
    } catch {
      if (activeRef.current && generationRef.current === generation) {
        failRecovery();
        setBusy(false);
      }
      return;
    }
    if (!activeRef.current || generationRef.current !== generation || result.status === 'stale') return;
    if (result.status === 'failed') {
      failRecovery(result.failure.operatorMessage);
      setBusy(false);
      return;
    }
    const committed = commitGateRef.current.commit(commitRequest, result.snapshot, (snapshot) => {
      setHealth(snapshot.health);
      setProviders(snapshot.providers);
      argsRef.current.onProviders(snapshot.providers);
      argsRef.current.onWorkspace(snapshot.workspace);
    });
    if (!committed) {
      setBusy(false);
      schedule(0);
      return;
    }
    attemptsRef.current = 0;
    transition('online');
    setOperatorMessage('');
    if (initialSessionIntentRef.current.isPending()) {
      try {
        const { sessionId, startInitialSession } = argsRef.current;
        if (initialSessionIntentRef.current.claim(sessionId)) {
          if (!sessionId) await startInitialSession();
        }
      } catch {
        if (activeRef.current) failRecovery();
        setBusy(false);
        return;
      }
    }
    if (!activeRef.current || generationRef.current !== generation) return;
    if (!commitGateRef.current.isCurrent(commitRequest)) {
      setBusy(false);
      schedule(0);
      return;
    }
    setBusy(false);
    schedule(PROBE_DELAY_MS);
  }

  function runRecovery(): Promise<void> {
    if (activeRunRef.current) return activeRunRef.current;
    clearTimer();
    const pending = performRecovery();
    activeRunRef.current = pending;
    void pending.then(
      () => { if (activeRunRef.current === pending) activeRunRef.current = null; },
      () => { if (activeRunRef.current === pending) activeRunRef.current = null; },
    );
    return pending;
  }

  function bootstrap(): void {
    transition('connecting');
    setOperatorMessage('Connecting to local runtime');
    void runRecovery();
  }

  function retry(): void {
    attemptsRef.current = 0;
    transition('reconnecting');
    setOperatorMessage('Local runtime is unavailable');
    void runRecovery();
  }

  useEffect(() => {
    activeRef.current = true;
    generationRef.current += 1;
    const unsubscribe = subscribeTransportFailures((failure) => {
      if (!activeRef.current) return;
      commitGateRef.current.invalidate();
      setHealth(null);
      transition('reconnecting');
      setOperatorMessage(transportMessage(failure.code));
      if (activeRunRef.current === null) schedule(0);
    });
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') clearTimer();
      else if (stateRef.current === 'reconnecting' || stateRef.current === 'offline') schedule(0);
      else if (stateRef.current === 'online') schedule(PROBE_DELAY_MS);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      commitGateRef.current.invalidate();
      recoveryRef.current?.invalidate();
      recoveryRef.current = null;
      activeRunRef.current = null;
      clearTimer();
      unsubscribe();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  return { health, providers, state, operatorMessage, busy, bootstrap, retry };
}
