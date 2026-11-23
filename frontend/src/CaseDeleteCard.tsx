import { useEffect, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { errorCodeOf } from './sessionResponse';
import { deleteCase, reviewCaseDelete, type CaseDeleteReview } from './caseDeleteApi';

/** The facts the user approves: which file, how big, what stays, and where it goes. */
export function CaseDeleteFacts({
  review,
  error,
  busy,
  onApprove,
  onCancel,
}: {
  readonly review: CaseDeleteReview | null;
  readonly error: string | null;
  readonly busy: boolean;
  readonly onApprove: () => void;
  readonly onCancel: () => void;
}) {
  const { t } = useLocale();
  return (
    <div className="case-delete-card" role="group" aria-label={t('caseDelete.title')}>
      <p className="case-delete-title">{t('caseDelete.title')}</p>
      {review === null ? (
        !error && <p className="chrome-hint">{t('caseDelete.loading')}</p>
      ) : (
        <>
          <p className="case-delete-name">
            <span>{review.name}</span>
            <span className="num">{t('caseDelete.size', { size: (review.size / 1024).toFixed(1) })}</span>
          </p>
          <p>{review.linked_results > 0 ? t('caseDelete.linked', { count: review.linked_results }) : t('caseDelete.linkedNone')}</p>
          <p>{t('caseDelete.recycle')}</p>
        </>
      )}
      {error && (
        <p className="case-delete-error" role="alert">
          {error === 'stale_source' ? t('caseDelete.stale') : t('caseDelete.failed')}
        </p>
      )}
      <div className="case-delete-actions">
        <button type="button" className="wb-btn" onClick={onCancel} autoFocus>{t('caseDelete.cancel')}</button>
        <button type="button" className="wb-btn wb-btn-danger" onClick={onApprove} disabled={busy || review === null}>{t('caseDelete.approve')}</button>
      </div>
    </div>
  );
}

/** Review one case, then delete it only on the user's Approve click. */
export default function CaseDeleteCard({
  rel,
  contextGeneration,
  onDone,
  onCancel,
}: {
  readonly rel: string;
  readonly contextGeneration: number;
  readonly onDone: (closed: boolean) => void;
  readonly onCancel: () => void;
}) {
  // The approval is bound to the workspace the user reviewed in, not whatever is open at click time.
  const [reviewedGeneration] = useState(contextGeneration);
  const [review, setReview] = useState<CaseDeleteReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    reviewCaseDelete(rel).then(
      (next) => { if (live) setReview(next); },
      (failure: unknown) => { if (live) setError(errorCodeOf(failure) ?? 'failed'); },
    );
    return () => { live = false; };
  }, [rel]);

  async function approve(): Promise<void> {
    if (review === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await deleteCase(review, reviewedGeneration);
      onDone(result.closed);
    } catch (failure) {
      setError(errorCodeOf(failure) ?? 'failed');
      setReview(null);
      if (errorCodeOf(failure) === 'stale_source') {
        reviewCaseDelete(rel).then(setReview, () => {});
      }
    } finally {
      setBusy(false);
    }
  }

  return <CaseDeleteFacts review={review} error={error} busy={busy} onApprove={() => void approve()} onCancel={onCancel} />;
}
