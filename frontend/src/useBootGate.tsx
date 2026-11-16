import { useEffect, useRef, useState, type ReactNode } from 'react';
import BootOverlay, { type BundleStatus } from './BootOverlay';
import { createBootGate, type BootFailReason } from './bootGate.mjs';
import { apiFetch } from './sessionTransport';
import { jsonOrThrow } from './sessionResponse';

export type BootRuntime = {
  readonly state: string;
  retry: () => void;
};

/** Boot overlay wiring, fed by the existing runtime loop — never a second
 *  health loop. Renders the overlay until ready lifts it away. */
export function useBootGate(runtime: BootRuntime): ReactNode {
  const gateRef = useRef(createBootGate());
  const [, setTick] = useState(0);
  const [retryCount, setRetryCount] = useState(0);
  const [gone, setGone] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [bundleStatus, setBundleStatus] = useState<BundleStatus>('idle');
  const [bundlePath, setBundlePath] = useState<string | null>(null);

  // An offline runtime is not a terminal failure: its background probes keep
  // running and a later online recovers the gate. Only the 45 s timeout fails.
  useEffect(() => {
    const gate = gateRef.current;
    if (runtime.state === 'online') gate.event('ready_ok');
    else gate.event('health_ok');
    gate.checkTimeout();
    setTick((n) => n + 1);
  }, [runtime.state]);

  useEffect(() => {
    if (!gateRef.current.isPending()) return;
    const timer = window.setInterval(() => {
      if (gateRef.current.checkTimeout()) setTick((n) => n + 1);
      if (!gateRef.current.isPending()) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [gone, retryCount]);

  const phase = gateRef.current.phase();
  const ready = phase === 'ready';
  const failure = gateRef.current.reason() as BootFailReason | null;

  useEffect(() => {
    if (!ready || gone) return;
    setLeaving(true);
    const timer = window.setTimeout(() => setGone(true), 240);
    return () => window.clearTimeout(timer);
  }, [ready, gone]);

  function retry(): void {
    gateRef.current.event('retry');
    setBundleStatus('idle');
    setBundlePath(null);
    setLeaving(false);
    setRetryCount((n) => n + 1);
    setTick((n) => n + 1);
    runtime.retry();
  }

  async function makeBundle(): Promise<void> {
    setBundleStatus('working');
    try {
      const body = (await jsonOrThrow(
        await apiFetch('/api/diagnostics/bundle', { method: 'POST' }),
      )) as { bundle_path: string };
      setBundlePath(body.bundle_path);
      setBundleStatus('ready');
    } catch {
      setBundleStatus('failed');
    }
  }

  if (gone) return null;
  return (
    <BootOverlay
      stage={phase === 'connecting' ? 'connecting' : 'starting'}
      failure={failure}
      leaving={leaving}
      bundlePath={bundlePath}
      bundleStatus={bundleStatus}
      onRetry={retry}
      onBundle={() => void makeBundle()}
    />
  );
}
