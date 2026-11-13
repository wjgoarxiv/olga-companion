import { readLocalStorage } from '../safeLocalStorage.ts';
import { hasUserResize, PANE_SPEC } from './paneSpec.ts';

export const COACHMARK_DISMISS_KEY = 'olga-companion.coachmark.resize';

export type CoachmarkVisibility = {
  readonly dismissed: boolean;
  readonly hasStoredWidth: boolean;
  readonly approvalActive: boolean;
};

/** First-run resize hint: shows once per profile, never over an approval. */
export function shouldShowResizeCoachmark(state: CoachmarkVisibility): boolean {
  if (state.dismissed) return false;
  if (state.approvalActive) return false;
  if (state.hasStoredWidth) return false;
  return true;
}

export function readCoachmarkVisibility(approvalActive: boolean): CoachmarkVisibility {
  return {
    dismissed: readLocalStorage(COACHMARK_DISMISS_KEY) === 'dismissed',
    hasStoredWidth: hasUserResize(PANE_SPEC.dock.storageKey),
    approvalActive,
  };
}
