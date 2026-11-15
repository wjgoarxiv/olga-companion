import { useMemo, useState } from 'react';
import { useLocale } from '../i18n/index.ts';
import { Button } from '../ui/Button';
import { ActivityLoader } from '../ui/ActivityLoader';
import { OperationStatus } from '../ui/OperationStatus';
import {
  fluidsDraftPreview,
  fluidsOpenMultiflash,
  fluidsPickupTab,
  type FluidDraftPreview,
  type FluidPickupResult,
} from '../workspaceApi';

/** Cross-view open request: useWorkbenchCommands handles the T5 command and
    the W2-L1 ①-entry event by selecting the workspace and raising this, so
    the panel opens even when the request lands from another view. */
let flowRequests = 0;
const flowListeners = new Set<() => void>();
export function requestFluidTableFlow(): void {
  flowRequests += 1;
  flowListeners.forEach((notify) => notify());
}
export function subscribeFluidTableFlow(notify: () => void): () => void {
  flowListeners.add(notify);
  return () => {
    flowListeners.delete(notify);
  };
}
export function getFluidTableFlowRequests(): number {
  return flowRequests;
}

/** Staged .tab preview for the workspace view to consume on mount. The banner
    navigates first, so the open request must survive the remount. Consumed
    (cleared) by whichever side opens it, so it never fires twice. */
let stagedPreviewRel: string | null = null;
export function stageTabPreview(rel: string): void {
  stagedPreviewRel = rel;
}
export function consumeStagedTabPreview(): string | null {
  const rel = stagedPreviewRel;
  stagedPreviewRel = null;
  return rel;
}

/** Documented backend contract (mfcmd p.84; fluid_table.py); the server
    validates authoritatively, these lists only shape the explicit choices. */
const MODELS = ['PR', 'PRA', 'SRK', 'RKSA', 'CPA'] as const;
const TEMPERATURE_UNITS = ['K', 'degC', 'degF', 'degR'] as const;
const PRESSURE_UNITS = [
  'Pa', 'kPa', 'Mpa', 'bar', 'barg', 'atm', 'atmg',
  'psi', 'psig', 'mmHg', 'inwg', 'at', 'atg',
] as const;

export interface FluidFlowChat {
  readonly input: string;
  readonly busy: boolean;
  readonly setInput: (value: string) => void;
}

export interface FluidTableFlowProps {
  readonly chat: FluidFlowChat;
  readonly activeCaseName: string | null;
  readonly onOpenDock: () => void;
  readonly onClose: () => void;
  readonly nativeTab?: boolean;
}

interface DraftRow {
  readonly key: number;
  name: string;
  fraction: string;
}

function parseGrid(text: string): number[] | null {
  const parts = text.split(/[\s,;]+/).map((part) => part.trim()).filter((part) => part !== '');
  if (parts.length === 0) return [];
  const values = parts.map((part) => Number(part));
  return values.some((value) => !Number.isFinite(value)) ? null : values;
}

let rowKeys = 0;

export default function FluidTableFlow(props: FluidTableFlowProps) {
  const { t } = useLocale();
  // Empty start: the app never fills a composition. Model stays null until
  // the user chooses explicitly — there is no default.
  const [label, setLabel] = useState('');
  const [model, setModel] = useState<string | null>(null);
  const [rows, setRows] = useState<readonly DraftRow[]>([]);
  const [temperaturesText, setTemperaturesText] = useState('');
  const [temperatureUnit, setTemperatureUnit] = useState<string>('K');
  const [pressuresText, setPressuresText] = useState('');
  const [pressureUnit, setPressureUnit] = useState<string>('bar');
  const [mflName, setMflName] = useState('');
  const [preview, setPreview] = useState<FluidDraftPreview | null>(null);
  const [previewKey, setPreviewKey] = useState('');
  const [previewError, setPreviewError] = useState('');
  const [previewBusy, setPreviewBusy] = useState(false);
  const [saveSent, setSaveSent] = useState(false);
  const [openBusy, setOpenBusy] = useState(false);
  const [openError, setOpenError] = useState('');
  const [openDone, setOpenDone] = useState(false);
  const [pickup, setPickup] = useState<FluidPickupResult | null>(null);
  const [pickupBusy, setPickupBusy] = useState(false);
  const [pickupError, setPickupError] = useState('');
  const [linkSent, setLinkSent] = useState(false);

  const moleSum = useMemo(
    () => rows.reduce((total, row) => total + (Number(row.fraction) || 0), 0),
    [rows],
  );
  const temperatures = useMemo(() => parseGrid(temperaturesText), [temperaturesText]);
  const pressures = useMemo(() => parseGrid(pressuresText), [pressuresText]);
  const mflRel = mflName.trim() || (label.trim() ? `${label.trim()}.mfl` : 'fluid.mfl');

  const draftInput = useMemo(() => {
    const trimmedLabel = label.trim();
    if (trimmedLabel === '' || model === null || rows.length === 0) return null;
    const components = rows.map((row) => ({ name: row.name.trim(), mole_fraction: Number(row.fraction) }));
    if (components.some((c) => c.name === '' || !Number.isFinite(c.mole_fraction))) return null;
    if (temperatures === null || pressures === null || temperatures.length < 2 || pressures.length < 2) return null;
    return {
      fluid_label: trimmedLabel,
      components,
      model,
      temperatures,
      temperature_unit: temperatureUnit,
      pressures,
      pressure_unit: pressureUnit,
      mfl_rel: mflRel,
    };
  }, [label, model, rows, temperatures, temperatureUnit, pressures, pressureUnit, mflRel]);
  const draftKey = draftInput === null ? '' : JSON.stringify(draftInput);
  const previewFresh = preview !== null && previewKey === draftKey && draftKey !== '';

  function gridError(values: number[] | null): string {
    if (values === null) return t('fluid.invalidNumber');
    if (values.length < 2) return t('fluid.gridCount');
    return '';
  }
  const temperaturesError = gridError(temperatures);
  const pressuresError = gridError(pressures);

  async function doPreview() {
    if (draftInput === null || props.chat.busy) return;
    setPreviewBusy(true);
    setPreviewError('');
    setPreview(null);
    try {
      const result = await fluidsDraftPreview(draftInput);
      setPreview(result);
      setPreviewKey(draftKey);
      setSaveSent(false);
      setOpenDone(false);
      setOpenError('');
      setPickup(null);
      setPickupError('');
      setLinkSent(false);
    } catch (cause) {
      setPreviewError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPreviewBusy(false);
    }
  }

  function doSave() {
    if (!previewFresh || preview === null || draftInput === null || props.chat.busy) return;
    const moleSum = draftInput.components.reduce((total, c) => total + c.mole_fraction, 0);
    props.chat.setInput(t('fluid.saveRequest', {
      label: draftInput.fluid_label,
      model: draftInput.model,
      count: draftInput.components.length,
      sum: moleSum.toFixed(6),
      temperatures: draftInput.temperatures.join(', '),
      temperatureUnit: draftInput.temperature_unit,
      pressures: draftInput.pressures.join(', '),
      pressureUnit: draftInput.pressure_unit,
      mfl: preview.mfl_rel,
    }));
    props.onOpenDock();
    setSaveSent(true);
  }

  async function doOpen() {
    if (preview === null || openBusy) return;
    setOpenBusy(true);
    setOpenError('');
    setOpenDone(false);
    try {
      await fluidsOpenMultiflash(preview.mfl_rel);
      setOpenDone(true);
    } catch (cause) {
      setOpenError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setOpenBusy(false);
    }
  }

  async function doPickup() {
    if (preview === null || pickupBusy) return;
    setPickupBusy(true);
    setPickupError('');
    setPickup(null);
    try {
      const result = await fluidsPickupTab(preview.mfl_rel, label.trim() || null);
      setPickup(result);
    } catch (cause) {
      setPickupError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPickupBusy(false);
    }
  }

  function doLink() {
    if (pickup?.link_proposal == null || props.activeCaseName === null || props.chat.busy) return;
    props.chat.setInput(t('fluid.linkRequest', {
      case: props.activeCaseName,
      tab: pickup.link_proposal.tab_path,
      label: pickup.link_proposal.fluid_label ?? label.trim(),
    }));
    props.onOpenDock();
    setLinkSent(true);
  }

  const linkReady = pickup !== null && pickup.valid && pickup.label_match
    && pickup.link_proposal !== null && props.activeCaseName !== null;

  return (
    <section
      className="fluid-flow" data-fluid-flow role="dialog" aria-label={t('fluid.title')}
      tabIndex={-1} ref={(node) => { node?.focus({ preventScroll: true }); }}
    >
      <header className="fluid-flow-head">
        <div>
          <h2>{t('fluid.title')}</h2>
          <p>{t(props.nativeTab ? 'fluid.subtitle.native' : 'fluid.subtitle')}</p>
        </div>
        <Button variant="quiet" onClick={props.onClose}>{t('fluid.closeAction')}</Button>
      </header>

      <div className="fluid-flow-grid">
        <label className="fluid-field">
          <span>{t('fluid.label')}</span>
          <input
            value={label} onChange={(event) => setLabel(event.target.value)}
            minLength={1} maxLength={64}
          />
          <em>{t('fluid.labelHint')}</em>
        </label>
        <fieldset className="fluid-field">
          <legend>{t('fluid.model')}</legend>
          <div className="fluid-models" role="radiogroup" aria-label={t('fluid.model')}>
            {MODELS.map((choice) => (
              <label key={choice} className="fluid-model">
                <input
                  type="radio" name="fluid-model" value={choice}
                  checked={model === choice} onChange={() => setModel(choice)}
                />
                <span>{choice}</span>
              </label>
            ))}
          </div>
          <em>{t('fluid.modelHint')}</em>
        </fieldset>
      </div>

      <section className="fluid-components" aria-label={t('fluid.components')}>
        <h3>{t('fluid.components')}</h3>
        {rows.length === 0 && <p className="fluid-empty">{t('fluid.emptyHint')}</p>}
        <ul>
          {rows.map((row) => (
            <li key={row.key} className="fluid-row">
              <label>
                <span>{t('fluid.name')}</span>
                <input
                  value={row.name} placeholder={t('fluid.namePlaceholder')}
                  onChange={(event) => setRows(rows.map((r) => (r.key === row.key ? { ...r, name: event.target.value } : r)))}
                />
              </label>
              <label>
                <span>{t('fluid.fraction')}</span>
                <input
                  value={row.fraction} inputMode="decimal" placeholder="0.5"
                  onChange={(event) => setRows(rows.map((r) => (r.key === row.key ? { ...r, fraction: event.target.value } : r)))}
                />
              </label>
              <Button
                variant="quiet"
                onClick={() => setRows(rows.filter((r) => r.key !== row.key))}
                aria-label={`${t('fluid.removeComponent')}: ${row.name || t('fluid.name')}`}
              >{t('fluid.removeComponent')}</Button>
            </li>
          ))}
        </ul>
        <div className="fluid-row-foot">
          <Button variant="secondary" onClick={() => { rowKeys += 1; setRows([...rows, { key: rowKeys, name: '', fraction: '' }]); }}>{t('fluid.addComponent')}</Button>
          <p aria-live="polite">{t('fluid.sum')}: {moleSum.toFixed(6)} · {t('fluid.sumHint')}</p>
        </div>
      </section>

      <div className="fluid-flow-grid">
        <label className="fluid-field">
          <span>{t('fluid.temperatures')}</span>
          <input value={temperaturesText} onChange={(event) => setTemperaturesText(event.target.value)} placeholder="20, 40, 60" />
          <em>{t('fluid.gridHint')}</em>
          {temperaturesText !== '' && temperaturesError !== '' && <strong className="fluid-error">{temperaturesError}</strong>}
        </label>
        <label className="fluid-field">
          <span>{t('fluid.pressures')}</span>
          <input value={pressuresText} onChange={(event) => setPressuresText(event.target.value)} placeholder="10, 50, 100" />
          <em>{t('fluid.gridHint')}</em>
          {pressuresText !== '' && pressuresError !== '' && <strong className="fluid-error">{pressuresError}</strong>}
        </label>
        <label className="fluid-field">
          <span>{t('fluid.tempUnit')}</span>
          <select value={temperatureUnit} onChange={(event) => setTemperatureUnit(event.target.value)}>
            {TEMPERATURE_UNITS.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
          </select>
        </label>
        <label className="fluid-field">
          <span>{t('fluid.pressureUnit')}</span>
          <select value={pressureUnit} onChange={(event) => setPressureUnit(event.target.value)}>
            {PRESSURE_UNITS.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
          </select>
        </label>
        <label className="fluid-field">
          <span>{t('fluid.mflFile')}</span>
          <input value={mflName} onChange={(event) => setMflName(event.target.value)} placeholder={label.trim() ? `${label.trim()}.mfl` : 'fluid.mfl'} />
        </label>
      </div>

      <div className="fluid-actions">
        <Button variant="primary" onClick={() => { void doPreview(); }} disabled={draftInput === null || props.chat.busy} busy={previewBusy} busyLabel={t('fluid.previewAction')}>{t('fluid.previewAction')}</Button>
        {previewError !== '' && <OperationStatus className="fluid-status" tone="error" title={previewError} detail="" />}
      </div>

      {preview !== null && (
        <section className="fluid-preview" aria-label={t('fluid.previewTitle')}>
          <h3>{t('fluid.previewTitle')}</h3>
          <pre>{preview.mfl_text}</pre>
          <div className="fluid-actions">
            <Button variant="primary" onClick={doSave} disabled={!previewFresh || props.chat.busy} title={t('fluid.saveHint')}>{t('fluid.saveAction')}</Button>
            {saveSent && <p className="fluid-note">{t('fluid.saveSent')}</p>}
          </div>
          <p className="fluid-note">{t('fluid.saveHint')}</p>
        </section>
      )}

      {preview !== null && (
        <section className="fluid-open" aria-label={t('fluid.openAction')}>
          <div className="fluid-actions">
            <Button variant="secondary" onClick={() => { void doOpen(); }} disabled={openBusy} busy={openBusy} busyLabel={t('fluid.openAction')}>{t('fluid.openAction')}</Button>
            {openDone && <p className="fluid-note">{t('fluid.manualSteps')}</p>}
            {openError !== '' && <OperationStatus className="fluid-status" tone="error" title={openError} detail="" />}
          </div>
          {!openDone && <p className="fluid-note">{t('fluid.manualSteps')}</p>}
        </section>
      )}

      {preview !== null && (
        <section className="fluid-pickup" aria-label={t('fluid.pickupTitle')}>
          <div className="fluid-actions">
            <Button variant="secondary" onClick={() => { void doPickup(); }} disabled={pickupBusy} busy={pickupBusy} busyLabel={t('fluid.ranAction')} title={t('fluid.ranHint')}>{t('fluid.ranAction')}</Button>
            {pickupBusy && <ActivityLoader className="fluid-loading" loadingLabel={t('fluid.pickupTitle')} />}
          </div>
          {pickupError !== '' && <OperationStatus className="fluid-status" tone="error" title={pickupError} detail="" />}
          {pickup !== null && !pickup.found && <p className="fluid-note">{t('fluid.pickupMissing')}</p>}
          {pickup !== null && pickup.found && (
            <OperationStatus
              className="fluid-status"
              tone={pickup.valid ? 'success' : 'info'}
              title={t('fluid.pickupTitle')}
              detail={[
                pickup.declared_label === null ? '' : `label: ${pickup.declared_label}`,
                ...pickup.errors.map((issue) => issue.message ?? ''),
                ...pickup.warnings.map((issue) => issue.message ?? ''),
              ].filter((line) => line !== '').join('\n')}
            />
          )}
          {linkReady && (
            <div className="fluid-actions">
              <Button variant="primary" onClick={doLink} disabled={props.chat.busy} title={t('fluid.linkHint')}>{t('fluid.linkAction')}</Button>
              {linkSent && <p className="fluid-note">{t('fluid.linkSent')}</p>}
            </div>
          )}
          {linkReady && !linkSent && <p className="fluid-note">{t('fluid.linkHint')}</p>}
        </section>
      )}
    </section>
  );
}
