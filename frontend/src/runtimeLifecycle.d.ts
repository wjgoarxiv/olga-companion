export type RuntimeState = 'connecting' | 'online' | 'reconnecting' | 'offline';

export type RuntimeEvent =
  | 'hydration_succeeded'
  | 'transport_failed'
  | 'retry_exhausted'
  | 'retry_requested';

export type RuntimeFailureInput =
  | { readonly kind: 'network'; readonly detail?: string }
  | { readonly kind: 'http'; readonly status: number; readonly detail?: string };

export type RuntimeFailure = {
  readonly code: 'local_runtime_offline' | 'local_session_expired' | 'local_runtime_unavailable';
  readonly state: 'offline' | 'reconnecting';
  readonly retryable: true;
  readonly operatorMessage:
    | 'Local runtime is offline'
    | 'Local session expired'
    | 'Local runtime is unavailable';
};

export type RetryPolicy = {
  readonly baseMs: number;
  readonly maxMs: number;
};

export type SafeHydrationStep = {
  readonly key: 'health' | 'token' | 'providers' | 'workspace';
  readonly method: 'GET';
  readonly protected: boolean;
};

export const SAFE_HYDRATION_STEPS: readonly SafeHydrationStep[];

export function classifyRuntimeFailure(input: RuntimeFailureInput): RuntimeFailure;
export function nextRuntimeState(state: RuntimeState, event: RuntimeEvent): RuntimeState;
export function retryDelayMs(attempt: number, policy: RetryPolicy): number;

export type RuntimeCommitGate = {
  begin(): number;
  isCurrent(request: number): boolean;
  commit<Snapshot>(request: number, snapshot: Snapshot, onCommit: (snapshot: Snapshot) => void): boolean;
  invalidate(): void;
};

export type InitialSessionIntent = {
  isPending(): boolean;
  claim(sessionId: string): boolean;
};

export function createRuntimeCommitGate(): RuntimeCommitGate;
export function createInitialSessionIntent(): InitialSessionIntent;

export type RuntimeOperations<Health, Token, Providers, Workspace> = {
  readonly health: () => Promise<Health>;
  readonly token: () => Promise<Token>;
  readonly providers: () => Promise<Providers>;
  readonly workspace: () => Promise<Workspace>;
};

export type RuntimeSnapshot<Health, Token, Providers, Workspace> = {
  readonly health: Health;
  readonly token: Token;
  readonly providers: Providers;
  readonly workspace: Workspace;
};

export type RecoveryResult<Health, Token, Providers, Workspace> =
  | { readonly status: 'recovered'; readonly snapshot: RuntimeSnapshot<Health, Token, Providers, Workspace> }
  | { readonly status: 'stale' }
  | { readonly status: 'failed'; readonly failure: RuntimeFailure };

export type RuntimeRecovery<Health, Token, Providers, Workspace> = {
  retry(): Promise<RecoveryResult<Health, Token, Providers, Workspace>>;
  invalidate(): void;
};

export function createRuntimeRecovery<Health, Token, Providers, Workspace>(options: {
  readonly operations: RuntimeOperations<Health, Token, Providers, Workspace>;
  readonly onCommit?: (snapshot: RuntimeSnapshot<Health, Token, Providers, Workspace>) => void;
  readonly classifyFailure?: (cause: unknown) => RuntimeFailure;
}): RuntimeRecovery<Health, Token, Providers, Workspace>;

export function shouldScheduleRuntimeProbe(input: {
  readonly visibility: DocumentVisibilityState;
  readonly state: RuntimeState;
}): boolean;

export function offlineProbeDelayMs(attempt: number): number;

export type ProbeClock = {
  setTimeout(handler: () => void, delayMs: number): unknown;
  clearTimeout(id: unknown): void;
};

export type ProbeTimer = {
  schedule(delayMs: number, task: () => void): void;
  cancel(): void;
};

export function createProbeTimer(clock?: ProbeClock): ProbeTimer;

export {
  classifyApprovalReceipt,
  classifyApprovalResumeFailure,
  createApprovalActionGuard,
  presentToolLifecycle,
  resolveApprovalCardLifecycle,
} from './approvalActionLifecycle';
export type {
  ApprovalActionGuard,
  ApprovalActionHandle,
  ToolLifecyclePresentation,
  ToolLifecycleState,
} from './approvalActionLifecycle';
