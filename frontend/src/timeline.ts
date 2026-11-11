import type { ToolStatus } from './ToolUnit';
import type { ApprovalRequest } from './types';
import { classifyApprovalReceipt } from './approvalActionLifecycle.mjs';
import type { ToolLifecycleState } from './approvalActionLifecycle';

export type TimelineItem =
  | { readonly kind: 'user'; readonly id: string; readonly text: string }
  | { readonly kind: 'assistant'; readonly id: string; readonly text: string }
  | { readonly kind: 'thinking'; readonly id: string; readonly text: string }
  | {
      readonly kind: 'tool';
      readonly id: string;
      readonly name: string;
      readonly callId: string;
      readonly status: ToolStatus;
      readonly args?: Record<string, unknown>;
      readonly result?: Record<string, unknown>;
    }
  | {
      readonly kind: 'approval';
      readonly id: string;
      readonly request: ApprovalRequest;
      readonly resolved: boolean;
      readonly resolution?: 'context-expired' | 'rejected';
      readonly lifecycle?: ToolLifecycleState;
      readonly recoverable?: boolean;
      readonly detail?: string;
      readonly result?: Record<string, unknown>;
    }
  | { readonly kind: 'error'; readonly id: string; readonly text: string };

let sequence = 0;

export function nextTimelineId(): string {
  const id = `i${sequence}`;
  sequence += 1;
  return id;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function recordOrEmpty(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function isSuccessfulToolStatus(status: string): boolean {
  return status === 'completed' || status === 'done';
}

export function rehydrateTimeline(records: readonly Record<string, unknown>[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const seenRecordIds = new Set<string>();
  for (const [index, record] of records.entries()) {
    const durableId = typeof record.record_id === 'string' ? record.record_id : '';
    if (durableId && seenRecordIds.has(durableId)) continue;
    if (durableId) seenRecordIds.add(durableId);
    const recordKind = String(record.record ?? '');
    const text = String(record.text ?? '');
    switch (recordKind) {
      case 'user':
        if (text) items.push({ kind: 'user', id: durableId || `user-${index}`, text });
        break;
      case 'assistant':
        if (text) items.push({ kind: 'assistant', id: durableId || `assistant-${index}`, text });
        break;
      case 'approval':
        foldApproval(items, record, durableId || `approval-${index}`);
        break;
      case 'event':
        applyEvent(items, record, durableId || `event-${index}`);
        break;
      case 'error':
        items.push({ kind: 'error', id: durableId || `error-${index}`, text: text || String(record.message ?? 'error') });
        break;
      case 'tombstone':
        items.length = 0;
        break;
      default:
        break;
    }
  }
  return items;
}

function foldApproval(items: TimelineItem[], record: Record<string, unknown>, id: string): void {
  const incoming = approvalItem(record, id);
  if (!incoming.resolved && incoming.lifecycle === 'awaiting-approval') {
    items.push(incoming);
    return;
  }
  const pendingId = incoming.request.pending_id;
  let found = -1;
  for (let candidate = items.length - 1; candidate >= 0; candidate -= 1) {
    const item = items[candidate];
    if (item?.kind !== 'approval') continue;
    const samePending = pendingId && item.request.pending_id
      ? item.request.pending_id === pendingId
      : item.request.call_id === incoming.request.call_id;
    if (samePending) {
      found = candidate;
      break;
    }
  }
  const existing = items[found];
  if (found < 0 || existing?.kind !== 'approval') {
    items.push(incoming);
    return;
  }
  items[found] = {
    kind: 'approval',
    id: existing.id,
    request: existing.request,
    resolved: incoming.resolved,
    ...(incoming.lifecycle ? { lifecycle: incoming.lifecycle } : {}),
    ...(incoming.recoverable ? { recoverable: true } : {}),
    ...(incoming.detail ? { detail: incoming.detail } : {}),
    ...(incoming.resolution ? { resolution: incoming.resolution } : {}),
    ...(incoming.result ? { result: incoming.result } : {}),
  };
}

function approvalItem(record: Record<string, unknown>, id: string): Extract<TimelineItem, { kind: 'approval' }> {
  const state = String(record.state ?? record.lifecycle ?? 'awaiting-approval');
  const lifecycle = classifyApprovalReceipt({ state, result: record.result });
  const recoverable = (lifecycle === 'dispatched' || lifecycle === 'running' || lifecycle === 'finalizing')
    && record.resume_allowed !== false;
  const terminalLifecycle = lifecycle === 'completed' || lifecycle === 'failed'
    || lifecycle === 'uncertain' || lifecycle === 'cancelled';
  const terminal = !recoverable && (record.resolved === true || terminalLifecycle);
  const unprovenPending = lifecycle === 'awaiting-approval' && !terminal && record.actionable !== true;
  const resolution = record.resolution === 'rejected' || state === 'rejected'
    ? 'rejected'
    : record.resolution === 'context-expired' || state === 'context-expired' || unprovenPending
      ? 'context-expired'
      : undefined;
  const resolved = terminal || unprovenPending;
  const base: Extract<TimelineItem, { kind: 'approval' }> = {
    kind: 'approval',
    id,
    request: {
      name: String(record.name ?? 'tool'),
      call_id: String(record.call_id ?? ''),
      pending_id: String(record.pending_id ?? ''),
      args: recordOrEmpty(record.args),
      ...(isRecord(record.display) ? { display: record.display } : {}),
      ...(typeof record.expires_at === 'number' ? { expires_at: record.expires_at } : {}),
    },
    ...(state === 'completed' || state === 'resumed' || state === 'approval_executed' || lifecycle === 'awaiting-approval'
      ? {}
      : { lifecycle }),
    ...(recoverable ? { recoverable: true } : {}),
    ...(isRecord(record.result) && Array.isArray(record.result.steps) ? { result: record.result } : {}),
    resolved,
  };
  return resolution ? { ...base, resolution } : base;
}

function applyEvent(items: TimelineItem[], record: Record<string, unknown>, id: string): void {
  const eventType = String(record.type ?? '');
  switch (eventType) {
    case 'tool_call': {
      const callId = String(record.call_id ?? '');
      items.push({
        kind: 'tool',
        id,
        name: String(record.name ?? 'tool'),
        callId,
        args: recordOrEmpty(record.args),
        status: toolStatus(record, 'running'),
      });
      break;
    }
    case 'tool_result': {
      const callId = String(record.call_id ?? '');
      const result = recordOrEmpty(record.result);
      let found = -1;
      for (let candidate = items.length - 1; candidate >= 0; candidate -= 1) {
        const item = items[candidate];
        if (item?.kind === 'tool' && item.callId === callId) {
          found = candidate;
          break;
        }
      }
      const status = toolStatus(record, 'error' in result || result.ok === false ? 'failed' : 'completed');
      if (found < 0) {
        items.push({ kind: 'tool', id, name: String(record.name ?? 'tool'), callId, result, status });
        break;
      }
      const item = items[found];
      if (item?.kind === 'tool') items[found] = { ...item, result, status };
      break;
    }
    case 'approval_required':
      foldApproval(items, record, id);
      break;
    case 'approval_executed':
      foldApproval(items, { ...record, state: 'completed' }, id);
      break;
    case 'error':
      items.push({ kind: 'error', id, text: String(record.message ?? 'error') });
      break;
    default:
      break;
  }
}

function toolStatus(record: Record<string, unknown>, fallback: ToolStatus): ToolStatus {
  const value = String(record.lifecycle ?? record.status ?? '');
  switch (value) {
    case 'awaiting-approval':
    case 'dispatched':
    case 'running':
    case 'finalizing':
    case 'completed':
    case 'failed':
    case 'uncertain':
    case 'cancelled':
      return value;
    case 'awaiting':
      return 'awaiting-approval';
    case 'done':
      return 'completed';
    case 'error':
      return 'failed';
    default:
      return fallback;
  }
}
