import { useEffect, useRef, useState, type ReactNode } from 'react';
import ShutdownOverlay, { type ShutdownPhase } from './ShutdownOverlay';
import { createShutdownFlow } from './shutdownFlow.mjs';
import { fetchRunHistory } from './runApi';
import { runStatusIsPollable } from './runPolling.mjs';

/** Shutdown wiring: the Rust close gate holds the window and emits
 *  app-close-requested; the overlay confirms (when a run is active) and
 *  drives saving -> stopping -> closing through the shutdown command. */
export function useShutdownGate(workspaceRoot: string): ReactNode {
  const flowRef = useRef(createShutdownFlow({ hasActiveRun: false }));
  const [phase, setPhase] = useState<ShutdownPhase>('idle');
  const [reason, setReason] = useState<string | null>(null);

  function sync(): void {
    setPhase(flowRef.current.phase() as ShutdownPhase);
    setReason(flowRef.current.reason());
  }

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    async function acknowledge(generation: number): Promise<void> {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('ack_close', { generation });
      } catch {
        return;
      }
    }
    // Without an active run there is nothing to confirm: a quiet shutdown
    // proceeds straight through saving -> stopping -> closing.
    async function handleCloseRequest(generation: number): Promise<void> {
      await acknowledge(generation);
      let hasActiveRun = false;
      try {
        const bounded = await Promise.race([
          fetchRunHistory(workspaceRoot, 1).catch(() => null),
          new Promise((resolve) => setTimeout(() => resolve(null), 1500)),
        ]);
        hasActiveRun = Array.isArray(bounded) && bounded.some((run) => runStatusIsPollable(run));
      } catch {
        hasActiveRun = false;
      }
      if (cancelled) return;
      flowRef.current = createShutdownFlow({ hasActiveRun });
      sync();
      if (flowRef.current.phase() === 'saving') {
        void proceed();
      }
    }
    void (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        const stop = await listen<number>('app-close-requested', (event) => {
          void handleCloseRequest(event.payload);
        });
        if (cancelled) {
          stop();
          return;
        }
        unlisten = stop;
      } catch {
        return;
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [workspaceRoot]);

  async function proceed(): Promise<void> {
    const flow = flowRef.current;
    flow.event('confirm_quit');
    sync();
    // A short visual beat so the saving stage paints; nothing is flushed
    // here — the work is already stored, the backend stop is the real step.
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (flowRef.current.phase() !== 'saving') return;
    flow.event('saved');
    sync();
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('shutdown_app');
      flow.event('stopped');
      sync();
      flow.event('exited');
      sync();
    } catch {
      flow.event('fail', 'stop_failed');
      sync();
    }
  }

  function stay(): void {
    // Tell the host this shutdown is abandoned: the close gate re-arms and
    // the pending fallback for this request must not exit.
    void (async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('cancel_close');
      } catch {
        return;
      }
    })();
    flowRef.current.event('confirm_stay');
    sync();
  }

  function retry(): void {
    flowRef.current.event('retry');
    sync();
    if (flowRef.current.phase() === 'saving') {
      void proceed();
    }
  }

  if (phase === 'idle') return null;
  return (
    <ShutdownOverlay
      phase={phase}
      failureReason={reason}
      onConfirmQuit={() => void proceed()}
      onStay={stay}
      onRetry={retry}
    />
  );
}
