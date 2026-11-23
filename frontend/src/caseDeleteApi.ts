import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

/** What the delete card shows before the user approves. Reads only. */
export interface CaseDeleteReview {
  readonly rel: string;
  readonly name: string;
  readonly size: number;
  readonly sha256: string;
  readonly linked_results: number;
}

export async function reviewCaseDelete(rel: string): Promise<CaseDeleteReview> {
  return (await jsonOrThrow(
    await apiFetch('/api/case-delete/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel }),
    }),
  )) as CaseDeleteReview;
}

/** The user's Approve click: the reviewed bytes go to the Recycle Bin. */
export async function deleteCase(review: CaseDeleteReview, contextGeneration: number): Promise<{ readonly closed: boolean }> {
  return (await jsonOrThrow(
    await apiFetch('/api/case-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel: review.rel, sha256: review.sha256, context_generation: contextGeneration, approved: true }),
    }),
  )) as { readonly closed: boolean };
}
