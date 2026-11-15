export interface ApprovalMintRequest {
  readonly epoch: number;
  readonly generation: number;
  readonly signal: AbortSignal;
}

export interface ApprovalMintLifecycle {
  begin(generation: number): ApprovalMintRequest;
  invalidate(): void;
  isCurrent(request: ApprovalMintRequest): boolean;
  finish(request: ApprovalMintRequest): void;
}

export function createApprovalMintLifecycle(): ApprovalMintLifecycle;

export function runApprovalMint<T>(
  lifecycle: ApprovalMintLifecycle,
  generation: number,
  getGeneration: () => number,
  mint: (signal: AbortSignal) => Promise<T>,
  handlers: {
    readonly onToken: (value: T, request: ApprovalMintRequest) => void | Promise<void>;
    readonly onError: (error: unknown, request: ApprovalMintRequest) => void;
    readonly onFinish: (request: ApprovalMintRequest) => void;
  },
): Promise<boolean>;
