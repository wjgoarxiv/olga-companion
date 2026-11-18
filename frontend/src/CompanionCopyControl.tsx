import { useEffect, useState } from 'react';
import { companionCopyApproved, companionCopyPreview } from './companionCopyApi';
import { referenceIsCopyable } from './companionCopyRules.ts';
import type { CompanionCopyPreview } from './runContracts';
import { useLocale } from './i18n/index.ts';
import { Button } from './ui/Button';
import { Select } from './ui/Select';
import { fetchWorkspace } from './workspaceApi';

type CopyStep =
  | { readonly kind: 'idle' }
  | { readonly kind: 'checking' }
  | { readonly kind: 'confirm'; readonly review: CompanionCopyPreview }
  | { readonly kind: 'copying'; readonly review: CompanionCopyPreview }
  | { readonly kind: 'done'; readonly copyTo: string };

type CompanionCopyControlProps = {
  readonly source: string;
  readonly reference: string;
  readonly previewBusy: boolean;
  readonly onPreviewAgain: () => void;
};

/** Fix one missing PVTFILE by copying a chosen workspace .tab next to the case. Nothing is copied before the
    user clicks Approve, and nothing is run afterwards: the user previews again with their own click. */
export function CompanionCopyControl({ source, reference, previewBusy, onPreviewAgain }: CompanionCopyControlProps) {
  const { t } = useLocale();
  const copyable = referenceIsCopyable(reference);
  const [tables, setTables] = useState<readonly string[] | null>(null);
  const [chosen, setChosen] = useState('');
  const [step, setStep] = useState<CopyStep>({ kind: 'idle' });
  const [problem, setProblem] = useState('');

  useEffect(() => {
    if (!copyable) return;
    let current = true;
    fetchWorkspace()
      .then((workspace) => {
        if (current) setTables(workspace.cases.filter((entry) => entry.suffix === '.tab').map((entry) => entry.rel));
      })
      .catch(() => { if (current) setTables([]); });
    return () => { current = false; };
  }, [copyable]);

  if (!copyable) return <p className="run-hint">{t('run.companionCopyUnavailable')}</p>;
  if (step.kind === 'done') {
    return (
      <div className="run-companion-copy" role="status">
        <p className="run-hint">{t('run.companionCopyDone', { to: step.copyTo })}</p>
        <Button variant="secondary" onClick={onPreviewAgain} disabled={previewBusy}>{t('run.companionCopyPreviewAgain')}</Button>
      </div>
    );
  }
  if (tables !== null && tables.length === 0) return <p className="run-hint">{t('run.companionCopyEmpty')}</p>;

  const request = { source, reference, tabSource: chosen };

  async function review() {
    if (!chosen) return;
    setProblem('');
    setStep({ kind: 'checking' });
    try {
      setStep({ kind: 'confirm', review: await companionCopyPreview(request) });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setStep({ kind: 'idle' });
    }
  }

  async function approve() {
    if (step.kind !== 'confirm') return;
    const reviewed = step.review;
    setProblem('');
    setStep({ kind: 'copying', review: reviewed });
    try {
      const result = await companionCopyApproved(request, { sha256: reviewed.sha256, size: reviewed.size });
      setStep({ kind: 'done', copyTo: result.copy_to });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setStep({ kind: 'idle' });
    }
  }

  const reviewing = step.kind === 'confirm' || step.kind === 'copying';
  const options = [
    { value: '', label: t('run.companionCopyPlaceholder') },
    ...(tables ?? []).map((rel) => ({ value: rel, label: rel })),
  ];

  return (
    <div className="run-companion-copy">
      <Select
        ariaLabel={t('run.companionCopyLabel', { reference })}
        value={chosen}
        onChange={(next) => { setChosen(next); setStep({ kind: 'idle' }); setProblem(''); }}
        options={options}
      />
      {!reviewing && (
        <Button variant="secondary" onClick={review} disabled={!chosen} busy={step.kind === 'checking'} busyLabel={t('run.companionCopyReviewing')}>
          {t('run.companionCopyReview')}
        </Button>
      )}
      {reviewing && (
        <div className="run-companion-copy-confirm">
          <p className="run-hint">
            {t('run.companionCopyConfirm', { from: step.review.tab_source, to: step.review.copy_to, size: t('saveas.bytesKB', { value: Math.max(1, Math.round(step.review.size / 1024)) }) })}
          </p>
          <div className="run-actions">
            <Button variant="primary" onClick={approve} busy={step.kind === 'copying'} busyLabel={t('run.companionCopyBusy')}>{t('run.companionCopyApprove')}</Button>
            <Button variant="quiet" onClick={() => setStep({ kind: 'idle' })} disabled={step.kind === 'copying'}>{t('run.companionCopyCancel')}</Button>
          </div>
        </div>
      )}
      {problem && <p className="run-hint" role="alert">{problem}</p>}
    </div>
  );
}
