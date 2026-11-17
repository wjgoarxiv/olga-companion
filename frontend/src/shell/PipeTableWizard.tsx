import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '../i18n/index.ts';
import { Button } from '../ui/Button';
import { OperationStatus } from '../ui/OperationStatus';
import { listPipeTables, previewPipeTable, type WorkspaceCase } from '../workspaceApi';
import {
  blankEnd,
  markPipeTableWizardShown,
  wizardBoundaries,
  wizardRequest,
  type EndEntry,
  type PipeTableFile,
  type PipeTablePreview,
} from '../pipeTableWizard';
import { formatDraftReason } from '../pipeTableDraft';

/** Window event the step ① detail raises; useWorkbenchCommands routes it to the palette command. */
export const PIPE_TABLE_WIZARD_EVENT = 'olga:open-pipe-table-wizard';

let wizardRequests = 0;
const wizardListeners = new Set<() => void>();
export function requestPipeTableWizard(): void {
  wizardRequests += 1;
  wizardListeners.forEach((notify) => notify());
}
export function subscribePipeTableWizard(notify: () => void): () => void {
  wizardListeners.add(notify);
  return () => {
    wizardListeners.delete(notify);
  };
}
export function getPipeTableWizardRequests(): number {
  return wizardRequests;
}

export interface PipeTableWizardProps {
  readonly chat: { readonly busy: boolean; readonly setInput: (value: string) => void };
  readonly cases: readonly WorkspaceCase[];
  readonly onOpenDock: () => void;
  readonly onClose: () => void;
}

type StepId = 'pick' | 'check' | 'ends' | 'send';
const STEPS: readonly StepId[] = ['pick', 'check', 'ends', 'send'];

export default function PipeTableWizard(props: PipeTableWizardProps) {
  const { t } = useLocale();
  const dialogRef = useRef<HTMLElement>(null);
  // Focus the dialog once on open; a callback ref would refocus it on every render and steal each keystroke.
  useEffect(() => { dialogRef.current?.focus({ preventScroll: true }); }, []);
  const [tables, setTables] = useState<readonly PipeTableFile[] | null>(null);
  const [listError, setListError] = useState('');
  const [path, setPath] = useState('');
  const [preview, setPreview] = useState<PipeTablePreview | null>(null);
  const [previewPath, setPreviewPath] = useState('');
  const [readBusy, setReadBusy] = useState(false);
  const [readError, setReadError] = useState('');
  const [ends, setEnds] = useState<readonly EndEntry[]>([]);
  const [tab, setTab] = useState('');
  const [endTime, setEndTime] = useState('');
  const [thermal, setThermal] = useState<'adiabatic' | 'ask' | ''>('');
  const [sent, setSent] = useState(false);
  useEffect(() => {
    markPipeTableWizardShown(true);
    return () => markPipeTableWizardShown(false);
  }, []);

  async function refresh() {
    setListError('');
    try {
      setTables(await listPipeTables());
    } catch (cause) {
      setListError(cause instanceof Error ? cause.message : String(cause));
    }
  }
  useEffect(() => { void refresh(); }, []);

  const tabs = props.cases.filter((entry) => entry.suffix === '.tab');
  const fresh = preview !== null && previewPath === path;
  const readable = fresh && preview.issues.length === 0 && preview.pipes > 0;
  const boundaries = useMemo(() => wizardBoundaries(ends), [ends]);
  const endTimeS = Number(endTime);
  const endTimeOk = endTime.trim() !== '' && Number.isFinite(endTimeS) && endTimeS > 0;

  const missing: string[] = [];
  if (!fresh) missing.push(t('pipeWizard.need.table'));
  else if (!readable) missing.push(t('pipeWizard.need.issues'));
  if (readable && boundaries === null) missing.push(t('pipeWizard.need.ends'));
  if (tab === '') missing.push(t('pipeWizard.need.tab'));
  if (!endTimeOk) missing.push(t('pipeWizard.need.endTime'));
  if (thermal === '') missing.push(t('pipeWizard.need.thermal'));
  const ready = missing.length === 0;

  const reached: Record<StepId, boolean> = {
    pick: path !== '',
    check: readable,
    ends: readable && boundaries !== null,
    send: sent,
  };
  const currentStep = STEPS.find((step) => !reached[step]) ?? 'send';

  async function doRead() {
    if (path === '' || readBusy) return;
    setReadBusy(true);
    setReadError('');
    setSent(false);
    try {
      const result = await previewPipeTable(path);
      setPreview(result);
      setPreviewPath(path);
      setEnds(result.ends.filter((end) => !end.has_values).map((end) => blankEnd(end.node)));
    } catch (cause) {
      setPreview(null);
      setReadError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setReadBusy(false);
    }
  }

  function update(node: string, patch: Partial<EndEntry>) {
    setSent(false);
    setEnds(ends.map((entry) => (entry.node === node ? { ...entry, ...patch } : entry)));
  }

  function doSend() {
    if (!ready || thermal === '' || props.chat.busy) return;
    props.chat.setInput(wizardRequest(t, { path, tab, endTimeS, thermal, boundaries }));
    props.onOpenDock();
    setSent(true);
  }

  return (
    <section
      className="fluid-flow pipe-wizard" data-pipe-wizard role="dialog" aria-label={t('pipeWizard.title')}
      tabIndex={-1} ref={dialogRef}
    >
      <header className="fluid-flow-head">
        <div>
          <h2>{t('pipeWizard.title')}</h2>
          <p>{t('pipeWizard.subtitle')}</p>
        </div>
        <Button variant="quiet" onClick={props.onClose}>{t('pipeWizard.close')}</Button>
      </header>

      <ol className="pipe-wizard-steps" aria-label={t('pipeWizard.stepsAria')}>
        {STEPS.map((step, index) => (
          <li
            key={step}
            className={reached[step] ? 'is-done' : step === currentStep ? 'is-current' : ''}
            aria-current={step === currentStep ? 'step' : undefined}
          >
            <span aria-hidden="true">{index + 1}</span>{t(`pipeWizard.step.${step}`)}
          </li>
        ))}
      </ol>

      <section className="pipe-wizard-block" aria-label={t('pipeWizard.step.pick')}>
        <label className="fluid-field">
          <span>{t('pipeWizard.pickLabel')}</span>
          <select value={path} onChange={(event) => { setPath(event.target.value); setSent(false); }}>
            <option value="">{t('pipeWizard.pickChoose')}</option>
            {(tables ?? []).map((table) => <option key={table.rel} value={table.rel}>{table.rel}</option>)}
          </select>
        </label>
        {tables !== null && tables.length === 0 && <p className="fluid-note">{t('pipeWizard.pickEmpty')}</p>}
        {listError !== '' && <OperationStatus className="fluid-status" tone="error" title={listError} detail="" />}
        <div className="fluid-actions">
          <Button variant="secondary" onClick={() => { void refresh(); }}>{t('pipeWizard.refresh')}</Button>
          <Button
            variant={fresh ? 'secondary' : 'primary'} onClick={() => { void doRead(); }}
            disabled={path === ''} busy={readBusy} busyLabel={t('pipeWizard.readAction')}
          >{t('pipeWizard.readAction')}</Button>
        </div>
        {readError !== '' && <OperationStatus className="fluid-status" tone="error" title={readError} detail="" />}
      </section>

      {fresh && (
        <section className="pipe-wizard-block" aria-label={t('pipeWizard.step.check')} aria-live="polite">
          <p className="pipe-wizard-summary">{t('pipeWizard.summary', {
            lines: preview.lines.length, pipes: preview.pipes, ends: preview.ends.length, junctions: preview.junctions.length,
          })}</p>
          {preview.ignored_columns.length > 0 && (
            <p className="fluid-note">{t('pipeWizard.ignored', { columns: preview.ignored_columns.join(', ') })}</p>
          )}
          {preview.issues.length > 0 && (
            <>
              <h3 className="pipe-draft-heading">{t('pipeWizard.issuesTitle')}</h3>
              <ul className="pipe-draft-issues">
                {preview.issues.map((issue, index) => (
                  <li key={index}>
                    {issue.row !== null && <span className="pipe-draft-issue-where">{t('pipeWizard.issueRow', { row: issue.row })}</span>}
                    <span className="pipe-draft-issue-reason">{formatDraftReason({ ...issue, field: '', params: {} }, t)}</span>
                  </li>
                ))}
              </ul>
              {preview.issues.some((issue) => issue.code === 'missing_flowpath') && (
                <p className="fluid-note">{t('pipeWizard.needLineColumn')}</p>
              )}
            </>
          )}
        </section>
      )}

      {readable && (
        <section className="pipe-wizard-block" aria-label={t('pipeWizard.endsTitle')}>
          <h3 className="pipe-draft-heading">{t('pipeWizard.endsTitle')}</h3>
          <p className="fluid-note">{ends.length === 0 ? t('pipeWizard.endsNone') : t('pipeWizard.endsHint')}</p>
          {preview.ends.filter((end) => end.has_values).map((end) => (
            <p key={end.node} className="pipe-wizard-given">{end.node} · {t('pipeWizard.endGiven')}</p>
          ))}
          <ul className="pipe-wizard-ends">
            {ends.map((entry) => (
              <li key={entry.node}>
                <fieldset>
                  <legend>{entry.node}</legend>
                  <label className="fluid-field">
                    <span>{t('pipeWizard.kind')}</span>
                    <select value={entry.kind} onChange={(event) => update(entry.node, { kind: event.target.value as EndEntry['kind'] })}>
                      <option value="">{t('pipeWizard.kindChoose')}</option>
                      <option value="source">{t('pipeWizard.kindSource')}</option>
                      <option value="sink">{t('pipeWizard.kindSink')}</option>
                    </select>
                  </label>
                  <label className="fluid-field">
                    <span>{t('pipeWizard.pressure')}</span>
                    <input inputMode="decimal" value={entry.pressureBar} onChange={(event) => update(entry.node, { pressureBar: event.target.value })} />
                  </label>
                  <label className="fluid-field">
                    <span>{t('pipeWizard.temperature')}</span>
                    <input inputMode="decimal" value={entry.temperatureC} onChange={(event) => update(entry.node, { temperatureC: event.target.value })} />
                  </label>
                  <label className="fluid-field">
                    <span>{t('pipeWizard.gasFraction')}</span>
                    <input inputMode="decimal" value={entry.gasFraction} onChange={(event) => update(entry.node, { gasFraction: event.target.value })} />
                    <em>{t('pipeWizard.gasFractionHint')}</em>
                  </label>
                  <label className="fluid-field">
                    <span>{t('pipeWizard.waterFraction')}</span>
                    <input inputMode="decimal" value={entry.waterFraction} onChange={(event) => update(entry.node, { waterFraction: event.target.value })} />
                    <em>{t('pipeWizard.waterFractionHint')}</em>
                  </label>
                </fieldset>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="pipe-wizard-block fluid-flow-grid" aria-label={t('pipeWizard.step.send')}>
        <label className="fluid-field">
          <span>{t('pipeWizard.tabLabel')}</span>
          <select value={tab} onChange={(event) => { setTab(event.target.value); setSent(false); }}>
            <option value="">{t('pipeWizard.pickChoose')}</option>
            {tabs.map((entry) => <option key={entry.rel} value={entry.rel}>{entry.rel}</option>)}
          </select>
          {tabs.length === 0 && <em>{t('pipeWizard.tabEmpty')}</em>}
        </label>
        <label className="fluid-field">
          <span>{t('pipeWizard.endTime')}</span>
          <input inputMode="decimal" value={endTime} placeholder="600" onChange={(event) => { setEndTime(event.target.value); setSent(false); }} />
        </label>
        <fieldset className="fluid-field">
          <legend>{t('pipeWizard.thermal')}</legend>
          <div className="fluid-models" role="radiogroup" aria-label={t('pipeWizard.thermal')}>
            {(['adiabatic', 'ask'] as const).map((choice) => (
              <label key={choice} className="fluid-model">
                <input type="radio" name="pipe-wizard-thermal" checked={thermal === choice} onChange={() => { setThermal(choice); setSent(false); }} />
                <span>{t(choice === 'adiabatic' ? 'pipeWizard.thermalAdiabatic' : 'pipeWizard.thermalAsk')}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </section>

      <div className="fluid-actions">
        <Button variant="primary" onClick={doSend} disabled={!ready || props.chat.busy} aria-describedby="pipe-wizard-missing">
          {t('pipeWizard.sendAction')}
        </Button>
        <p id="pipe-wizard-missing" className="fluid-note" aria-live="polite">
          {sent ? t('pipeWizard.sent') : ready ? t('pipeWizard.sendHint') : t('pipeWizard.missing', { items: missing.join(', ') })}
        </p>
      </div>
    </section>
  );
}
