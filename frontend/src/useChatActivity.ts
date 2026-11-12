import { useEffect, useState } from 'react';
import { eventActivityPhase, presentChatActivity, type ChatActivityPresentation } from './progressPresentation';
import type { AgentEvent } from './types';

type ActiveTurn = {
  readonly phase: string;
  readonly startedAtMs: number;
  readonly cancellable: boolean;
};

export function useChatActivity() {
  const [turn, setTurn] = useState<ActiveTurn | null>(null);
  const [nowMs, setNowMs] = useState(0);

  useEffect(() => {
    if (!turn) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [turn?.startedAtMs]);

  function begin() {
    const startedAtMs = Date.now();
    setNowMs(startedAtMs);
    setTurn({ phase: 'connecting', startedAtMs, cancellable: true });
  }

  function observe(event: AgentEvent) {
    const phase = eventActivityPhase(event);
    setTurn((current) => (current && current.phase !== phase ? { ...current, phase } : current));
  }

  function finish() {
    setTurn(null);
  }

  const reducedMotion = typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const activity: ChatActivityPresentation | null = turn
    ? presentChatActivity({
        phase: turn.phase,
        started_at_ms: turn.startedAtMs,
        now_ms: nowMs || turn.startedAtMs,
        cancellable: turn.cancellable,
        reduced_motion: reducedMotion,
      })
    : null;

  return { activity, begin, finish, observe };
}
