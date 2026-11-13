import { useEffect, useRef, useState } from 'react';
import * as session from './session';
import { playCue } from './sound.mjs';
import type { AgentEvent } from './types';
import { useChatActivity } from './useChatActivity';
import { useChatDraft } from './useChatDraft';

interface ChatStreamArgs {
  readonly effort: string;
  readonly model: string;
  readonly provider: string;
  readonly onEvent: (event: AgentEvent) => void;
  readonly onError: (error: unknown) => void;
  readonly onFinished: () => void;
}

export function useChatStream(args: ChatStreamArgs) {
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);
  const activity = useChatActivity();
  const draft = useChatDraft();
  const argsRef = useRef(args);
  argsRef.current = args;

  function changeBusy(value: boolean): void {
    busyRef.current = value;
    setBusy(value);
  }

  async function run(sessionId: string, message: string): Promise<void> {
    if (busyRef.current) return;
    const controller = new AbortController();
    const epoch = ++epochRef.current;
    abortRef.current = controller;
    activity.begin();
    changeBusy(true);
    // Only how the turn settled is kept; no event, delta or draft plays a cue.
    let outcome = null as 'done' | 'error' | null;
    try {
      await session.streamChat(
        sessionId,
        message,
        argsRef.current.provider,
        argsRef.current.model,
        (event) => {
          if (epochRef.current !== epoch) return;
          activity.observe(event);
          draft.observe(event);
          if (event.type === 'done') outcome = 'done';
          else if (event.type === 'error') outcome = 'error';
          else if (event.type === 'approval_required') outcome = null;
          argsRef.current.onEvent(event);
        },
        controller.signal,
        argsRef.current.effort,
      );
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        outcome = 'error';
        argsRef.current.onError(error);
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        activity.finish();
        draft.clear();
        changeBusy(false);
        if (outcome === 'done') playCue('done');
        else if (outcome === 'error') playCue('error');
        argsRef.current.onFinished();
      }
    }
  }

  async function stop(sessionId: string): Promise<void> {
    const controller = abortRef.current;
    if (!controller) return;
    try {
      await session.stopChatResponse(sessionId);
    } catch {
      // The local abort still releases the composer if the runtime disappeared.
    }
    if (abortRef.current === controller) controller.abort();
  }

  function invalidate(): void {
    epochRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    activity.finish();
    draft.clear();
    changeBusy(false);
  }

  useEffect(() => () => {
    epochRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    busyRef.current = false;
  }, []);

  return {
    activity: activity.activity,
    draft: draft.draft,
    busy,
    isBusy: () => busyRef.current,
    invalidate,
    run,
    setBusy: changeBusy,
    stop,
  };
}
