import { useEffect, useRef, useState } from 'react';
import { classifyApprovalReceipt } from './approvalActionLifecycle';
import { nextQueuedMessage } from './activeWorkQueue';
import * as session from './session';
import { type TimelineItem, nextTimelineId, recordOrEmpty } from './timeline';
import type { AgentEvent, ApprovalRequest } from './types';
import { useActiveWorkQueue } from './useActiveWorkQueue';
import { useApprovalContinuation } from './useApprovalContinuation';
import { useChatScroll } from './useChatScroll';
import { useChatSessions } from './useChatSessions';
import { useChatStream } from './useChatStream';

interface UseChatControllerArgs {
  readonly effort: string;
  readonly model: string;
  readonly provider: string;
  readonly refreshWorkspace: () => void;
  readonly t: (key: string, vars?: Record<string, string | number>) => string;
  readonly workspaceGeneration: number;
}

export function useChatController(args: UseChatControllerArgs) {
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [input, setInput] = useState('');
  const approvalCallIds = useRef<Set<string>>(new Set());
  const lastUserRef = useRef('');
  const workspaceGenerationRef = useRef(args.workspaceGeneration);
  const previousWorkspaceGenerationRef = useRef(args.workspaceGeneration);
  workspaceGenerationRef.current = args.workspaceGeneration;
  const { atBottom, markAtBottom, onScroll, scrollRef, scrollToBottom } = useChatScroll();
  const activeQueue = useActiveWorkQueue();
  const stream = useChatStream({
    effort: args.effort,
    model: args.model,
    provider: args.provider,
    onError: reportError,
    onEvent: handleEvent,
    onFinished: finishTurn,
  });
  const sessions = useChatSessions({
    isBusy: stream.isBusy,
    onError: reportError,
    onReset: resetConversation,
    onRestore: restoreConversation,
  });
  const approvals = useApprovalContinuation({
    approvalCallIds,
    executeApproval: (request, generation, signal) => session.executeApproval(
      request.pending_id, sessions.sessionId, request.call_id, generation, signal,
    ),
    handleEvent,
    rejectApproval: (request, generation, signal) => session.rejectApproval(
      request.pending_id, sessions.sessionId, request.call_id, generation, signal,
    ),
    refreshWorkspace: args.refreshWorkspace,
    reportError,
    resumeApproval: (request, generation, onEvent, signal) => session.resumeApproval(
      request.pending_id, sessions.sessionId, request.call_id, generation, onEvent, signal,
    ),
    sessionId: sessions.sessionId,
    setBusy: stream.setBusy,
    updateApproval,
    updateTool,
    workspaceGeneration: workspaceGenerationRef,
  });

  useEffect(() => {
    if (previousWorkspaceGenerationRef.current === args.workspaceGeneration) return;
    previousWorkspaceGenerationRef.current = args.workspaceGeneration;
    invalidateContext();
  }, [args.workspaceGeneration]);

  function push(item: TimelineItem): void {
    setTimeline((items) => [...items, item]);
  }

  function reportError(error: unknown): void {
    push({ kind: 'error', id: nextTimelineId(), text: error instanceof Error ? error.message : String(error) });
  }

  function updateTool(
    callId: string,
    patch: Partial<Extract<TimelineItem, { kind: 'tool' }>>,
  ): void {
    setTimeline((items) => {
      const reverseIndex = [...items].reverse().findIndex(
        (item) => item.kind === 'tool' && item.callId === callId,
      );
      if (reverseIndex === -1) return items;
      const index = items.length - 1 - reverseIndex;
      const item = items[index];
      if (!item || item.kind !== 'tool') return items;
      return items.map((candidate, candidateIndex) => (
        candidateIndex === index ? { ...item, ...patch } : candidate
      ));
    });
  }

  function updateApproval(callId: string, patch: Partial<Extract<TimelineItem, { kind: 'approval' }>>): void {
    setTimeline((items) => items.map((item) => (
      item.kind === 'approval' && item.request.call_id === callId
        ? { ...item, ...patch }
        : item
    )));
  }

  function handleEvent(event: AgentEvent): void {
    const data = event.data;
    if (event.type === 'text' || (event.type === 'done' && data.text)) {
      const text = String(data.text ?? '');
      if (!text) return;
      setTimeline((items) => {
        const last = items[items.length - 1];
        return last?.kind === 'assistant'
          ? [...items.slice(0, -1), { ...last, text }]
          : [...items, { kind: 'assistant', id: nextTimelineId(), text }];
      });
    } else if (event.type === 'thinking') {
      const text = String(data.text ?? '');
      if (text) push({ kind: 'thinking', id: nextTimelineId(), text });
    } else if (event.type === 'tool_call') {
      push({
        kind: 'tool',
        id: nextTimelineId(),
        name: String(data.name),
        callId: String(data.call_id ?? ''),
        status: 'running',
      });
    } else if (event.type === 'tool_result') {
      const result = recordOrEmpty(data.result);
      const callId = String(data.call_id ?? '');
      const failed = 'error' in result || result.ok === false;
      const state = failed
        ? 'failed'
        : classifyApprovalReceipt({ state: result.state ?? result.lifecycle ?? 'completed', result });
      updateTool(callId, {
        status: failed && approvalCallIds.current.has(callId) ? 'awaiting-approval' : state,
        ...(failed && approvalCallIds.current.has(callId) ? {} : { result }),
      });
    } else if (event.type === 'approval_required') {
      const callId = String(data.call_id);
      approvalCallIds.current.add(callId);
      updateTool(callId, { status: 'awaiting-approval' });
      push({
        kind: 'approval',
        id: nextTimelineId(),
        resolved: false,
        lifecycle: 'awaiting-approval',
        request: {
          name: String(data.name),
          call_id: callId,
          pending_id: String(data.pending_id),
          args: recordOrEmpty(data.args),
          display: recordOrEmpty(data.display),
          ...(typeof data.expires_at === 'number' ? { expires_at: data.expires_at } : {}),
        },
      });
    } else if (event.type === 'error') {
      reportError(String(data.message ?? 'error'));
    }
  }

  async function sendNow(message: string): Promise<void> {
    if (!message.trim() || stream.isBusy()) return;
    const generation = workspaceGenerationRef.current;
    const sessionId = await sessions.ensureSession(message).catch((error: unknown) => { reportError(error); return null; });
    // The user opened another chat or switched workspace while this waited: the
    // message was never sent, so the draft stays where it is.
    if (!sessionId || stream.isBusy()) return;
    if (workspaceGenerationRef.current !== generation) return reportError(args.t('chat.workspaceChanged'));
    lastUserRef.current = message;
    push({ kind: 'user', id: nextTimelineId(), text: message });
    setInput('');
    markAtBottom();
    await stream.run(sessionId, message);
  }

  function finishTurn(): void {
    args.refreshWorkspace();
    window.setTimeout(() => {
      if (approvalCallIds.current.size > 0) return;
      const queued = activeQueue.takeNext();
      // A message queued in another chat is dropped, never delivered to this one.
      if (queued && (!queued.sessionId || queued.sessionId === sessions.currentId())) void sendNow(queued.message);
    }, 0);
  }

  function queueInput(policy: 'steer' | 'next'): void {
    if (!input.trim()) return;
    activeQueue.enqueue(input, policy, sessions.currentId());
    setInput('');
  }

  function invalidateContext(): void {
    approvals.invalidate();
    stream.invalidate();
    approvalCallIds.current.clear();
    setTimeline((items) => items.map((item) => (
      item.kind === 'approval' && !item.resolved
        ? { ...item, resolved: true, resolution: 'context-expired' }
        : item
    )));
  }

  function resetConversation(): void {
    approvals.invalidate();
    stream.invalidate();
    setTimeline([]);
    approvalCallIds.current = new Set();
    lastUserRef.current = '';
    markAtBottom();
  }

  function restoreConversation(items: TimelineItem[]): void {
    approvals.invalidate();
    approvalCallIds.current = new Set();
    const lastUser = [...items].reverse().find((item) => item.kind === 'user');
    lastUserRef.current = lastUser?.kind === 'user' ? lastUser.text : '';
    setTimeline(items);
    markAtBottom();
  }

  async function rejectAndApplySteer(request: ApprovalRequest): Promise<void> {
    const next = nextQueuedMessage(activeQueue.queued);
    if (!next || next.policy !== 'steer') return;
    await approvals.reject(request);
    activeQueue.remove(next.id);
    await sendNow(next.message);
  }

  const pendingApproval = [...timeline].reverse().find(
    (item): item is Extract<TimelineItem, { kind: 'approval' }> => item.kind === 'approval' && !item.resolved,
  );

  return {
    activity: stream.activity, draft: stream.draft,
    atBottom,
    busy: stream.busy,
    input,
    lastUserText: lastUserRef.current,
    pendingApproval: pendingApproval?.request,
    queued: activeQueue.queued,
    scrollRef,
    sessionId: sessions.sessionId,
    sessions: sessions.sessions,
    timeline,
    approve: approvals.approve,
    deleteChat: sessions.deleteChat,
    editQueued: activeQueue.update,
    loadSession: sessions.loadSession,
    newChat: sessions.newChat,
    queueNext: () => queueInput('next'),
    recoverApproval: approvals.recover,
    reject: approvals.reject,
    rejectAndApplySteer,
    regenerate: () => { if (lastUserRef.current) void stream.run(sessions.sessionId, lastUserRef.current); },
    removeQueued: activeQueue.remove,
    reportError,
    retryError: () => { void sendNow(lastUserRef.current); },
    send: sendNow,
    setInput,
    startInitialSession: sessions.startInitialSession,
    steerNow: () => queueInput('steer'),
    invalidateContext,
    stop: () => { void stream.stop(sessions.sessionId); },
    onScroll,
    scrollToBottom,
    submitInput: () => { stream.busy ? queueInput('next') : void sendNow(input); },
  };
}
