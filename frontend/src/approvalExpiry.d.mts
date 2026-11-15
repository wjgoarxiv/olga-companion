export const APPROVAL_EXPIRED_SENTENCE: string;

export function describeApprovalExpiry(
  expiresAt: number | undefined,
  nowMs: number,
): { expired: boolean; line: string; time: string };

export type ApprovalUnavailableResult = Record<string, unknown> & {
  ok: false;
  code: 'approval_unavailable';
  error: string;
};

export function approvalUnavailableResult(message: unknown): ApprovalUnavailableResult | null;

export function approvalStatusLabel(
  status: string,
  result?: Record<string, unknown> | null,
): string | null;
