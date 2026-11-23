import type { TimelineItem } from './timeline';

type ApprovalItem = Extract<TimelineItem, { kind: 'approval' }>;
export type ClosedApprovalsEntry = { readonly kind: 'closed-approvals'; readonly id: string; readonly items: readonly ApprovalItem[] };
export function isClosedApproval(item: TimelineItem): item is ApprovalItem;
export function foldClosedApprovals(items: readonly TimelineItem[]): (TimelineItem | ClosedApprovalsEntry)[];
