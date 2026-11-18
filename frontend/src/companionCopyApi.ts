import type { CompanionCopyPreview, CompanionCopyResult } from './runContracts';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export type CompanionCopyRequest = {
  readonly source: string;
  readonly reference: string;
  readonly tabSource: string;
};

/** What the user reviewed; the server refuses the copy unless the table still holds exactly these bytes. */
export type CompanionCopyReviewed = { readonly sha256: string; readonly size: number };

function body(request: CompanionCopyRequest, approved: boolean, reviewed?: CompanionCopyReviewed): string {
  return JSON.stringify({
    source: request.source,
    reference: request.reference,
    tab_source: request.tabSource,
    approved,
    ...(reviewed ? { sha256: reviewed.sha256, size: reviewed.size } : {}),
  });
}

/** Describe the copy for the approval step; the server writes nothing. */
export async function companionCopyPreview(request: CompanionCopyRequest): Promise<CompanionCopyPreview> {
  return (await jsonOrThrow(
    await apiFetch('/api/run/companion-copy/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body(request, false),
    }),
  )) as CompanionCopyPreview;
}

/** Copy the chosen table. Only called from the explicit "Approve copy" click. */
export async function companionCopyApproved(
  request: CompanionCopyRequest,
  reviewed: CompanionCopyReviewed,
): Promise<CompanionCopyResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/run/companion-copy/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body(request, true, reviewed),
    }),
  )) as CompanionCopyResult;
}
