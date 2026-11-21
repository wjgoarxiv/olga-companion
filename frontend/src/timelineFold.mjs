import { APPROVAL_EXPIRED_SENTENCE } from './approvalExpiry.mjs';

/** A request that can no longer be approved: its time ran out, or the case or workspace changed. */
export function isClosedApproval(item) {
  return item.kind === 'approval' && item.resolved === true
    && (item.resolution === 'context-expired' || item.detail === APPROVAL_EXPIRED_SENTENCE);
}

/** Consecutive closed requests become one read-only entry; everything else is passed through as is. */
export function foldClosedApprovals(items) {
  const out = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (!isClosedApproval(item)) out.push(item);
    else if (last?.kind === 'closed-approvals') out[out.length - 1] = { ...last, items: [...last.items, item] };
    else out.push({ kind: 'closed-approvals', id: `closed-${item.id}`, items: [item] });
  }
  return out;
}
