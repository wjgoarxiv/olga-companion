import type { AgentEvent, AgentEventType } from './types';

export class EventStreamError extends Error {
  readonly name = 'EventStreamError';
  readonly status: number;

  constructor(status: number) {
    super(`Event stream failed: HTTP ${status}`);
    this.status = status;
  }
}

export class ApprovalResumeError extends Error {
  readonly name = 'ApprovalResumeError';
  readonly resumeAllowed: boolean | undefined;
  readonly state: string | undefined;
  readonly code: string | undefined;

  constructor(message: string, state?: string, resumeAllowed?: boolean, code?: string) {
    super(message);
    this.state = state;
    this.resumeAllowed = resumeAllowed;
    this.code = code;
  }
}

async function resumeRejection(response: Response): Promise<ApprovalResumeError> {
  let record: Record<string, unknown> = {};
  try {
    const parsed: unknown = await response.json();
    if (isRecord(parsed)) record = parsed;
  } catch {
    return new ApprovalResumeError(`Event stream failed: HTTP ${response.status}`);
  }
  const state = typeof record.state === 'string' ? record.state : 'failed';
  const detail = typeof record.detail === 'string'
    ? record.detail
    : typeof record.message === 'string' ? record.message : `HTTP ${response.status}`;
  const code = typeof record.code === 'string' && record.code ? record.code : '';
  const marked = code ? `${detail} (HTTP ${response.status} ${code})` : detail;
  return new ApprovalResumeError(
    marked,
    state,
    record.resume_allowed === true,
    code || undefined,
  );
}

export async function consumeApprovalResumeEvents(
  response: Response,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  if (!response.ok) throw await resumeRejection(response);
  let continuationError: Error | undefined;
  await consumeAgentEvents(response, (event) => {
    onEvent(event);
    if (event.type === 'error') {
      const message = typeof event.data.message === 'string'
        ? event.data.message
        : 'Assistant continuation failed';
      const state = typeof event.data.state === 'string' ? event.data.state : undefined;
      const resumeAllowed = typeof event.data.resume_allowed === 'boolean'
        ? event.data.resume_allowed
        : undefined;
      continuationError = new ApprovalResumeError(message, state, resumeAllowed);
    }
  });
  if (continuationError) throw continuationError;
}

export async function consumeAgentEvents(
  response: Response,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  if (!response.ok || !response.body) throw new EventStreamError(response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let separator = buffer.indexOf('\n\n');
    while (separator !== -1) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      emitFrame(frame, onEvent);
      separator = buffer.indexOf('\n\n');
    }
  }
}

function emitFrame(frame: string, onEvent: (event: AgentEvent) => void): void {
  let type = '';
  let data: Record<string, unknown> = {};
  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) type = line.slice(7).trim();
    if (line.startsWith('data: ')) {
      const raw = line.slice(6);
      try {
        const parsed: unknown = JSON.parse(raw);
        data = isRecord(parsed) ? parsed : { raw };
      } catch {
        data = { raw };
      }
    }
  }
  const eventType = parseEventType(type);
  if (eventType) onEvent({ type: eventType, data });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseEventType(value: string): AgentEventType | null {
  switch (value) {
    case 'open':
    case 'phase':
    case 'draft':
    case 'text':
    case 'thinking':
    case 'tool_call':
    case 'tool_result':
    case 'approval_required':
    case 'done':
    case 'error':
      return value;
    default:
      return null;
  }
}
