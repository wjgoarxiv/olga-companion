export type ToolLifecycleState =
  | 'awaiting-approval'
  | 'dispatched'
  | 'running'
  | 'finalizing'
  | 'completed'
  | 'failed'
  | 'uncertain'
  | 'cancelled';

export type ToolLifecyclePresentation = {
  readonly state: ToolLifecycleState;
  readonly label: string;
  readonly terminal: boolean;
  readonly recoverable: boolean;
};

export function presentToolLifecycle(input: { readonly state: ToolLifecycleState }): ToolLifecyclePresentation;
export function classifyApprovalReceipt(input: unknown): ToolLifecycleState;
export function classifyApprovalResumeFailure(error: unknown):
  | { readonly state: 'uncertain'; readonly recoverable: false }
  | { readonly state: 'finalizing'; readonly recoverable: true };
export function resolveApprovalCardLifecycle(input: {
  readonly lifecycle?: ToolLifecycleState;
  readonly resolved: boolean;
  readonly resolution?: 'context-expired' | 'rejected';
}): ToolLifecycleState;

export type ApprovalActionHandle = {
  readonly identity: string;
  readonly phase: 'dispatch' | 'resume';
  readonly epoch: number;
  readonly signal: AbortSignal;
};

export type ApprovalActionGuard = {
  claimDispatch(identity: string): ApprovalActionHandle | null;
  beginResume(identity: string): ApprovalActionHandle | null;
  finish(handle: ApprovalActionHandle): void;
  finishResume(handle: ApprovalActionHandle): void;
  invalidate(): void;
  isCurrent(handle: ApprovalActionHandle): boolean;
};

export function createApprovalActionGuard(): ApprovalActionGuard;
