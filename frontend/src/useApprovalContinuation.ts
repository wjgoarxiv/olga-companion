import { useRef } from 'react';
import type { MutableRefObject } from 'react';
import {
  classifyApprovalReceipt,
  classifyApprovalResumeFailure,
  createApprovalActionGuard,
} from './approvalActionLifecycle';
import type { ToolLifecycleState } from './approvalActionLifecycle';
import type { ApprovalExecution } from './session';
import type { TimelineItem } from './timeline';
import { approvalUnavailableResult } from './approvalExpiry.mjs';
import { PLAN_ACTION, planSettledState } from './planApproval.mjs';
import type { AgentEvent, ApprovalRequest } from './types';

type ApprovalItem = Extract<TimelineItem, { readonly kind: 'approval' }>;
type ToolItem = Extract<TimelineItem, { readonly kind: 'tool' }>;

interface ApprovalContinuationArgs {
  readonly approvalCallIds: MutableRefObject<Set<string>>;
  readonly executeApproval: (request: ApprovalRequest, generation: number, signal: AbortSignal) => Promise<ApprovalExecution>;
  readonly handleEvent: (event: AgentEvent) => void;
  readonly rejectApproval: (request: ApprovalRequest, generation: number, signal: AbortSignal) => Promise<ApprovalExecution>;
  readonly refreshWorkspace: () => void;
  readonly reportError: (error: unknown) => void;
  readonly sessionId: string;
  readonly setBusy: (busy: boolean) => void;
  readonly updateApproval: (callId: string, patch: Partial<ApprovalItem>) => void;
  readonly updateTool: (callId: string, patch: Partial<ToolItem>) => void;
  readonly workspaceGeneration: MutableRefObject<number>;
  readonly resumeApproval: (request: ApprovalRequest, generation: number, onEvent: (event: AgentEvent) => void, signal: AbortSignal) => Promise<void>;
}

function identity(request: ApprovalRequest, sessionId: string, generation: number): string {
  return `${sessionId}:${request.pending_id}:${request.call_id}:${generation}`;
}

/** A plan result carries one state per step; keep it so the card can show them. */
function planResult(result: Record<string, unknown> | undefined): { readonly result: Record<string, unknown> } | Record<string, never> {
  return result && Array.isArray(result.steps) ? { result } : {};
}

function isTerminal(state: ToolLifecycleState): boolean {
  switch (state) {
    case 'completed':
    case 'failed':
    case 'cancelled':
      return true;
    case 'uncertain':
    case 'awaiting-approval':
    case 'dispatched':
    case 'running':
    case 'finalizing':
      return false;
  }
}

export function useApprovalContinuation(args: ApprovalContinuationArgs) {
  const guardRef = useRef(createApprovalActionGuard());
  // A stopped plan settles failed, never completed, even when recovery resumes it later.
  const stoppedPlansRef = useRef(new Set<string>());

  function finishApproval(request: ApprovalRequest, state: ToolLifecycleState, result?: Record<string, unknown>): void {
    args.approvalCallIds.current.delete(request.call_id);
    args.updateTool(request.call_id, { status: state, ...(result ? { result } : {}) });
    const errorText = typeof result?.error === 'string' ? result.error : '';
    args.updateApproval(request.call_id, {
      lifecycle: state,
      recoverable: false,
      resolved: isTerminal(state),
      ...(errorText ? { detail: errorText } : {}),
      ...planResult(result),
      ...(state === 'cancelled' ? { resolution: 'rejected' } : {}),
    });
  }

  async function resume(request: ApprovalRequest, generation: number): Promise<boolean> {
    const actionIdentity = identity(request, args.sessionId, generation);
    const handle = guardRef.current.beginResume(actionIdentity);
    if (!handle) return false;
    args.updateApproval(request.call_id, { lifecycle: 'finalizing', recoverable: false, detail: '' });
    try {
      await args.resumeApproval(request, generation, args.handleEvent, handle.signal);
      if (!guardRef.current.isCurrent(handle)) return false;
      if (stoppedPlansRef.current.has(request.call_id)) {
        args.updateTool(request.call_id, { status: 'failed' });
        args.updateApproval(request.call_id, { lifecycle: 'failed', recoverable: false, resolved: true });
        return true;
      }
      args.updateTool(request.call_id, { status: 'completed' });
      args.updateApproval(request.call_id, { lifecycle: 'completed', recoverable: false, resolved: true });
      return true;
    } catch (error: unknown) {
      if (!guardRef.current.isCurrent(handle)) return false;
      const failure = classifyApprovalResumeFailure(error);
      if (!failure.recoverable) {
        finishApproval(request, failure.state);
        args.updateApproval(request.call_id, {
          detail: error instanceof Error ? error.message : String(error),
        });
        return false;
      }
      args.updateApproval(request.call_id, {
        lifecycle: failure.state,
        recoverable: failure.recoverable,
        resolved: false,
        detail: error instanceof Error ? error.message : String(error),
      });
      return false;
    } finally {
      guardRef.current.finish(handle);
    }
  }

  async function approve(request: ApprovalRequest): Promise<void> {
    const generation = args.workspaceGeneration.current;
    const handle = guardRef.current.claimDispatch(identity(request, args.sessionId, generation));
    if (!handle) return;
    args.setBusy(true);
    args.updateApproval(request.call_id, { lifecycle: 'dispatched', recoverable: false, detail: '' });
    args.updateTool(request.call_id, { status: 'dispatched' });
    try {
      const execution = await args.executeApproval(request, generation, handle.signal);
      if (!guardRef.current.isCurrent(handle)) return;
      const state = classifyApprovalReceipt(execution);
      args.refreshWorkspace();
      if (request.name === PLAN_ACTION && planSettledState(execution.result) === 'failed') {
        stoppedPlansRef.current.add(request.call_id);
      }
      if (!isTerminal(state) || execution.resume_allowed === true) {
        args.updateTool(request.call_id, { status: 'finalizing', ...(execution.result ? { result: execution.result } : {}) });
        args.updateApproval(request.call_id, { lifecycle: 'finalizing', recoverable: false, resolved: false, detail: '', ...planResult(execution.result) });
        await resume(request, generation);
        return;
      }
      finishApproval(request, state, execution.result);
    } catch (error: unknown) {
      if (!guardRef.current.isCurrent(handle)) return;
      const unavailable = approvalUnavailableResult(error instanceof Error ? error.message : String(error));
      if (unavailable) {
        finishApproval(request, 'failed', unavailable);
        return;
      }
      const state = error instanceof Error && 'state' in error && typeof error.state === 'string'
        ? classifyApprovalReceipt({ state: error.state }) : 'uncertain';
      const steps = error instanceof Error && 'steps' in error && Array.isArray(error.steps) ? error.steps : undefined;
      finishApproval(request, state, { error: error instanceof Error ? error.message : String(error), ...(steps ? { steps } : {}) });
      args.reportError(error);
    } finally {
      guardRef.current.finish(handle);
      args.setBusy(false);
    }
  }

  async function reject(request: ApprovalRequest): Promise<void> {
    const generation = args.workspaceGeneration.current;
    const handle = guardRef.current.claimDispatch(identity(request, args.sessionId, generation));
    if (!handle) return;
    args.setBusy(true);
    try {
      const execution = await args.rejectApproval(request, generation, handle.signal);
      if (!guardRef.current.isCurrent(handle)) return;
      if (execution.result?.code === 'approval_unavailable') {
        finishApproval(request, 'failed', execution.result);
        return;
      }
      finishApproval(request, 'cancelled');
    } catch (error: unknown) {
      if (!guardRef.current.isCurrent(handle)) return;
      const unavailable = approvalUnavailableResult(error instanceof Error ? error.message : String(error));
      if (unavailable) {
        finishApproval(request, 'failed', unavailable);
        return;
      }
      finishApproval(request, 'uncertain');
      args.reportError(error);
    } finally {
      guardRef.current.finish(handle);
      args.setBusy(false);
    }
  }

  async function recover(request: ApprovalRequest): Promise<void> {
    args.setBusy(true);
    await resume(request, args.workspaceGeneration.current);
    args.setBusy(false);
  }

  return { approve, invalidate: () => guardRef.current.invalidate(), recover, reject };
}
