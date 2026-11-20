import { useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { Button } from './ui/Button';
import { apiFetch } from './sessionTransport';
import { openStopRemedy, type StopRemedyAnswer } from './stopRemedyModel.mjs';

type StopRemedyProps = {
  readonly runId: string;
  readonly activeCase?: string | null;
  readonly onOpenEditRow: (rel: string, rowId: string) => void;
};

async function getRemedy(url: string): Promise<StopRemedyAnswer> {
  const response = await apiFetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as StopRemedyAnswer;
}

/** Points at the edit-table row the stop names; nothing is filled in and nothing is saved. */
export function StopRemedy({ runId, activeCase, onOpenEditRow }: StopRemedyProps) {
  const { t } = useLocale();
  const [busy, setBusy] = useState(false);
  const [reasonKey, setReasonKey] = useState<string | null>(null);
  async function open() {
    setBusy(true);
    setReasonKey(null);
    try {
      const result = await openStopRemedy(runId, { get: getRemedy, activeCase, open: onOpenEditRow });
      setReasonKey(result.reasonKey);
    } catch {
      setReasonKey('run.stop.remedy.reason.failed');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="run-stop-remedy">
      <Button variant="secondary" onClick={() => { void open(); }} busy={busy} busyLabel={t('run.stop.remedy.busy')}>
        {t('run.stop.remedy.open')}
      </Button>
      <p className="run-stop-remedy-reason" role="status">{reasonKey ? t(reasonKey) : null}</p>
    </div>
  );
}
