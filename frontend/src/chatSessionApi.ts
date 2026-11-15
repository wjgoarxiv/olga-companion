import type { AgentEvent } from './types';
import { chatRequestBody } from './chatRequest.ts';
import { currentLocale } from './i18n/index.ts';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';
import { consumeAgentEvents, consumeApprovalResumeEvents } from './sseClient';

export interface SessionMeta {
  readonly session_id: string;
  readonly title: string;
  readonly updated_ms?: number;
  readonly tombstoned?: boolean;
  readonly deleted?: boolean;
  readonly state?: string;
}

export async function newSession(title = ''): Promise<string> {
  const body = (await jsonOrThrow(
    await apiFetch('/api/chat/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  )) as { session_id: string };
  return body.session_id;
}

export async function fetchSessions(): Promise<SessionMeta[]> {
  const body = (await jsonOrThrow(await apiFetch('/api/chat/sessions'))) as { sessions: SessionMeta[] };
  return body.sessions;
}

export async function fetchSessionHistory(id: string): Promise<Record<string, unknown>[]> {
  const body = (await jsonOrThrow(await apiFetch(`/api/chat/session/${encodeURIComponent(id)}`))) as {
    records: Record<string, unknown>[];
  };
  return body.records;
}

export async function deleteSession(id: string): Promise<{ deleted: boolean }> {
  return (await jsonOrThrow(
    await apiFetch(`/api/chat/session/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  )) as { deleted: boolean };
}

export async function stopChatResponse(sessionId: string): Promise<{ stopped: boolean }> {
  return (await jsonOrThrow(
    await apiFetch('/api/chat/response/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    }),
  )) as { stopped: boolean };
}

export interface ApprovalExecution {
  readonly name?: string;
  readonly call_id: string;
  readonly pending_id?: string;
  readonly result?: Record<string, unknown>;
  readonly resume_allowed?: boolean;
  readonly state: string;
}

export class ApprovalTransitionError extends Error {
  readonly name = 'ApprovalTransitionError';

  constructor(
    message: string,
    readonly state: string,
    readonly resumeAllowed: boolean,
    readonly steps?: readonly unknown[],
  ) {
    super(message);
  }
}

type ApprovalIdentity = {
  readonly pending_id: string;
  readonly session_id: string;
  readonly call_id: string;
  readonly context_generation: number;
};

function approvalIdentity(pendingId: string, sessionId: string, callId: string, contextGeneration: number): ApprovalIdentity {
  return { pending_id: pendingId, session_id: sessionId, call_id: callId, context_generation: contextGeneration };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function approvalResponse(response: Response): Promise<ApprovalExecution> {
  const body: unknown = await response.json().catch(() => ({}));
  const record = isRecord(body) ? body : {};
  const state = typeof record.state === 'string' ? record.state : 'failed';
  if (!response.ok) {
    const detail = typeof record.detail === 'string'
      ? record.detail
      : typeof record.message === 'string' ? record.message : `HTTP ${response.status}`;
    const code = typeof record.code === 'string' && record.code ? record.code : '';
    const marked = code ? `${detail} (HTTP ${response.status} ${code})` : detail;
    throw new ApprovalTransitionError(marked, state, record.resume_allowed === true, Array.isArray(record.steps) ? record.steps : undefined);
  }
  return {
    ...(typeof record.name === 'string' ? { name: record.name } : {}),
    ...(typeof record.pending_id === 'string' ? { pending_id: record.pending_id } : {}),
    ...(isRecord(record.result) ? { result: record.result } : {}),
    ...(typeof record.resume_allowed === 'boolean' ? { resume_allowed: record.resume_allowed } : {}),
    call_id: typeof record.call_id === 'string' ? record.call_id : '',
    state,
  };
}

export async function executeApproval(pendingId: string, sessionId: string, callId: string, contextGeneration: number, signal?: AbortSignal): Promise<ApprovalExecution> {
  return approvalResponse(await apiFetch('/api/approvals/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pending_id: pendingId, session_id: sessionId, call_id: callId, context_generation: contextGeneration }),
      signal,
    }));
}

export async function rejectApproval(pendingId: string, sessionId: string, callId: string, contextGeneration: number, signal?: AbortSignal): Promise<ApprovalExecution> {
  return approvalResponse(await apiFetch('/api/approvals/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...approvalIdentity(pendingId, sessionId, callId, contextGeneration), reason: 'Rejected by user' }),
    signal,
  }));
}

export async function resumeApproval(
  pendingId: string,
  sessionId: string,
  callId: string,
  contextGeneration: number,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await consumeApprovalResumeEvents(await apiFetch('/api/approvals/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(approvalIdentity(pendingId, sessionId, callId, contextGeneration)),
    signal,
  }), onEvent);
}

/** Stream one chat turn as SSE, invoking onEvent for each parsed event.
 *  Provider selection rides x-llm-* headers (resolver precedence). */
export async function streamChat(
  sessionId: string,
  message: string,
  provider: string,
  model: string,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
  variant?: string,
): Promise<void> {
  const response = await apiFetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-llm-provider': provider,
      'x-llm-model': model,
      ...(variant ? { 'x-llm-variant': variant } : {}),
    },
    body: JSON.stringify(chatRequestBody(sessionId, message, currentLocale())),
    signal,
  });
  await consumeAgentEvents(response, onEvent);
}
