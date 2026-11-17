import { useEffect, useState } from 'react';
import { useLocale } from '../i18n/index.ts';
import { Button } from '../ui/Button';
import { OperationStatus } from '../ui/OperationStatus';
import type { PipeTableFile } from '../pipeTableWizard';
import {
  importRequest,
  isTabFileName,
  issueText,
  parseFraction,
  suggestedLabel,
  suggestedTabName,
  type TabImportPreview,
} from '../tabImport.ts';
import { tabImportPreview } from '../tabImportApi';
import { listPipeTables } from '../workspaceApi';

export interface TabImportPanelProps {
  readonly chat: { readonly busy: boolean; readonly setInput: (value: string) => void };
  readonly onOpenDock: () => void;
}

/** Make a .tab from property values the user already has. Reading is free; the file is written only after the approval card. */
export default function TabImportPanel(props: TabImportPanelProps) {
  const { t } = useLocale();
  const [tables, setTables] = useState<readonly PipeTableFile[] | null>(null);
  const [listError, setListError] = useState('');
  const [path, setPath] = useState('');
  const [label, setLabel] = useState('');
  const [tabName, setTabName] = useState('');
  const [waterText, setWaterText] = useState('');
  const [preview, setPreview] = useState<TabImportPreview | null>(null);
  const [previewKey, setPreviewKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);

  async function refresh() {
    setListError('');
    try {
      setTables(await listPipeTables());
    } catch (cause) {
      setListError(cause instanceof Error ? cause.message : String(cause));
    }
  }
  useEffect(() => { void refresh(); }, []);

  const water = parseFraction(waterText);
  const waterBad = waterText.trim() !== '' && water === null;
  const key = `${path}|${label.trim()}|${water ?? ''}`;
  const fresh = preview !== null && previewKey === key;
  const needsWater = preview !== null && preview.summary.phase === 'THREE';
  const tabOk = isTabFileName(tabName);
  const ready = fresh && preview !== null && preview.ok && tabOk && !props.chat.busy;

  function pick(rel: string) {
    setPath(rel);
    setSent(false);
    setLabel(rel === '' ? '' : suggestedLabel(rel));
    setTabName(rel === '' ? '' : suggestedTabName(rel));
    setPreview(null);
    setWaterText('');
  }

  async function doRead() {
    if (path === '' || label.trim() === '' || waterBad || busy) return;
    setBusy(true);
    setError('');
    setSent(false);
    try {
      setPreview(await tabImportPreview({ path, fluidLabel: label.trim(), waterFraction: water }));
      setPreviewKey(key);
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  function doSend() {
    if (!ready) return;
    props.chat.setInput(importRequest(t, { source: path, tab: tabName.trim(), label: label.trim(), waterFraction: water }));
    props.onOpenDock();
    setSent(true);
  }

  const summary = preview?.summary;
  return (
    <details className="tab-import" data-tab-import>
      <summary>{t('tabImport.title')}</summary>
      <p className="fluid-note">{t('tabImport.subtitle')}</p>
      <p className="fluid-note">{t('tabImport.units')}</p>

      <div className="fluid-flow-grid">
        <label className="fluid-field">
          <span>{t('tabImport.pickLabel')}</span>
          <select value={path} onChange={(event) => pick(event.target.value)}>
            <option value="">{t('tabImport.pickChoose')}</option>
            {(tables ?? []).map((table) => <option key={table.rel} value={table.rel}>{table.rel}</option>)}
          </select>
          {tables !== null && tables.length === 0 && <em>{t('tabImport.pickEmpty')}</em>}
        </label>
        <label className="fluid-field">
          <span>{t('tabImport.label')}</span>
          <input value={label} maxLength={64} onChange={(event) => { setLabel(event.target.value); setSent(false); }} />
          <em>{t('fluid.labelHint')}</em>
        </label>
        <label className="fluid-field">
          <span>{t('tabImport.tabFile')}</span>
          <input value={tabName} onChange={(event) => { setTabName(event.target.value); setSent(false); }} />
          {tabName.trim() !== '' && !tabOk && <strong className="fluid-error">{t('tabImport.tabFileBad')}</strong>}
        </label>
        {(needsWater || waterText !== '') && (
          <label className="fluid-field">
            <span>{t('tabImport.water')}</span>
            <input inputMode="decimal" value={waterText} placeholder="0.4" onChange={(event) => { setWaterText(event.target.value); setSent(false); }} />
            <em>{t('tabImport.waterHint')}</em>
            {waterBad && <strong className="fluid-error">{t('tabImport.waterBad')}</strong>}
          </label>
        )}
      </div>
      {listError !== '' && <OperationStatus className="fluid-status" tone="error" title={listError} detail="" />}

      <div className="fluid-actions">
        <Button variant="secondary" onClick={() => { void refresh(); }}>{t('tabImport.refresh')}</Button>
        <Button
          variant={fresh ? 'secondary' : 'primary'} onClick={() => { void doRead(); }}
          disabled={path === '' || label.trim() === '' || waterBad} busy={busy} busyLabel={t('tabImport.readAction')}
        >{t('tabImport.readAction')}</Button>
      </div>
      {error !== '' && <OperationStatus className="fluid-status" tone="error" title={error} detail="" />}

      {fresh && preview !== null && summary !== undefined && (
        <section className="tab-import-result" aria-label={t('tabImport.resultTitle')} aria-live="polite">
          <p className="tab-import-summary">{t('tabImport.summary', {
            pressures: summary.pressure_points, temperatures: summary.temperature_points, points: summary.points,
          })}</p>
          {summary.columns.length > 0 && (
            <p className="fluid-note">{t('tabImport.columns', { columns: summary.columns.join(', '), phase: summary.phase === 'THREE' ? 3 : 2 })}</p>
          )}
          {summary.source_units.pressure !== undefined && summary.source_units.pressure !== '' && (
            <p className="fluid-note">{t('tabImport.axisUnits', {
              pressure: summary.source_units.pressure, temperature: summary.source_units.temperature ?? '',
            })}</p>
          )}
          {summary.ignored_columns.length > 0 && (
            <p className="fluid-note">{t('tabImport.ignored', { columns: summary.ignored_columns.join(', ') })}</p>
          )}
          {preview.issues.length > 0 && (
            <>
              <h3 className="tab-import-heading">{t('tabImport.issuesTitle')}</h3>
              <ul className="tab-import-issues">
                {preview.issues.map((issue, index) => <li key={index}>{issueText(t, issue)}</li>)}
              </ul>
            </>
          )}
          {preview.ok && (
            <OperationStatus className="fluid-status" tone="success" title={t('tabImport.okTitle')} detail={t('tabImport.okDetail')} />
          )}
          {preview.ok && preview.text_head !== null && <pre className="tab-import-head">{preview.text_head}</pre>}
        </section>
      )}

      <div className="fluid-actions">
        <Button variant="primary" onClick={doSend} disabled={!ready} title={t('tabImport.saveHint')}>{t('tabImport.saveAction')}</Button>
        {sent && <p className="fluid-note">{t('tabImport.saveSent')}</p>}
      </div>
      <p className="fluid-note">{t('tabImport.saveHint')}</p>
    </details>
  );
}
