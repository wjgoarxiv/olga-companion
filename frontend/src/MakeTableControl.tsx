import { useEffect, useState } from 'react';
import { makeableName } from './companionCopyRules.ts';
import { makeTable, makeTableCandidates, type MakeTableResult } from './makeTableApi';
import { useLocale } from './i18n/index.ts';
import { Button } from './ui/Button';
import { Select } from './ui/Select';

type MakeStep =
  | { readonly kind: 'idle' }
  | { readonly kind: 'confirm' }
  | { readonly kind: 'making' }
  | { readonly kind: 'done'; readonly result: MakeTableResult };

type MakeTableControlProps = {
  readonly source: string;
  readonly reference: string;
  readonly previewBusy: boolean;
  readonly onPreviewAgain: () => void;
};

/** Make one missing PVTFILE from an .mfl in the case folder with the Multiflash engine. Nothing is written before
    the user clicks Make the table, and nothing is run afterwards: the user previews again with their own click. */
export function MakeTableControl({ source, reference, previewBusy, onPreviewAgain }: MakeTableControlProps) {
  const { t } = useLocale();
  const name = makeableName(reference);
  const [candidates, setCandidates] = useState<readonly string[]>([]);
  const [chosen, setChosen] = useState('');
  const [step, setStep] = useState<MakeStep>({ kind: 'idle' });
  const [problem, setProblem] = useState('');

  useEffect(() => {
    if (!name) return undefined;
    let current = true;
    makeTableCandidates(source)
      .then((names) => {
        if (!current) return;
        setCandidates(names);
        const stem = name.replace(/\.tab$/i, '').toLowerCase();
        setChosen(names.find((item) => item.replace(/\.mfl$/i, '').toLowerCase() === stem) ?? names[0] ?? '');
      })
      .catch(() => { if (current) setCandidates([]); });
    return () => { current = false; };
  }, [source, name]);

  if (!name || candidates.length === 0) return null;
  if (step.kind === 'done') {
    const { result } = step;
    return (
      <div className="run-companion-copy" role="status">
        <p className="run-hint">
          {t('run.makeTableDone', { name: result.tab_name, label: result.fluid_label, p: result.points.pressures, t: result.points.temperatures })}
          {result.grid_source === 'default' ? ` ${t('run.makeTableDefaultGrid')}` : ''}
        </p>
        <Button variant="secondary" onClick={onPreviewAgain} disabled={previewBusy}>{t('run.companionCopyPreviewAgain')}</Button>
      </div>
    );
  }

  async function approve() {
    setProblem('');
    setStep({ kind: 'making' });
    try {
      setStep({ kind: 'done', result: await makeTable(source, reference, chosen) });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setStep({ kind: 'idle' });
    }
  }

  const confirming = step.kind === 'confirm' || step.kind === 'making';
  return (
    <div className="run-companion-copy">
      {candidates.length > 1 && (
        <Select
          ariaLabel={t('run.makeTableFrom', { name })}
          value={chosen}
          onChange={(next) => { setChosen(next); setStep({ kind: 'idle' }); setProblem(''); }}
          options={candidates.map((item) => ({ value: item, label: item }))}
        />
      )}
      {!confirming && (
        <Button variant="secondary" onClick={() => setStep({ kind: 'confirm' })} disabled={!chosen}>
          {t('run.makeTable', { mfl: chosen })}
        </Button>
      )}
      {confirming && (
        <div className="run-companion-copy-confirm">
          <p className="run-hint">{t('run.makeTableConfirm', { mfl: chosen, name })}</p>
          <div className="run-actions">
            <Button variant="primary" onClick={approve} busy={step.kind === 'making'} busyLabel={t('run.makeTableBusy')}>{t('run.makeTableApprove')}</Button>
            <Button variant="quiet" onClick={() => setStep({ kind: 'idle' })} disabled={step.kind === 'making'}>{t('run.companionCopyCancel')}</Button>
          </div>
        </div>
      )}
      {problem && <p className="run-hint" role="alert">{problem}</p>}
    </div>
  );
}
