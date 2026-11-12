import { RunSweepStatus } from './RunSweepStatus';
import { RunStatePill } from './RunStatePill';
import { SweepParameterPicker } from './SweepParameterPicker';
import { SweepValueBuilder } from './SweepValueBuilder';
import type { RunActions } from './useRunActions';
import type { RunViewModel } from './runViewModel';
import type { RunViewState } from './useRunViewState';
import { useLocale } from './i18n/index.ts';
import { runStateLabel } from './runReason.ts';
import { Button } from './ui/Button';
import { OperationStatus } from './ui/OperationStatus';
import { Receipt } from './ui/Receipt';

type RunSweepPanelProps = {
  readonly state: RunViewState;
  readonly actions: RunActions;
  readonly model: RunViewModel;
};

export function RunSweepPanel({ state, actions, model }: RunSweepPanelProps) {
  const {
    active, sweepSupervisionUnknown, sweepStarting, sweepStatus, sweepPreview,
    sweepParameter, sweepValues, sweepPreviewing, sweepCancelling,
    setSweepParameter, setSweepValues,
  } = state;
  const { doSweepPreview, doSweepRun, doSweepCancel, resetSweepPlan } = actions;
  const {
    safetyOperationActive, runReady, sweepSpec, sweepCaseCount, sweepCancellable,
    requestOperationActive,
  } = model;
  const { t } = useLocale();
  const sweepState = (sweepStatus ?? sweepPreview)?.state ?? null;
  const stateKey = sweepSupervisionUnknown ? 'last_known' : sweepStarting ? 'starting' : sweepState || 'ready';

  return (
    <section className="run-panel sweep-panel" aria-label={t('run.panelSweepAria')}>
      <header className="run-panel-head">
        <span>{t('run.sweepRecipe')}</span>
        <RunStatePill statusLabel={runStateLabel(stateKey, t)} statusClass={`run-${sweepSupervisionUnknown ? 'planned' : sweepStarting ? 'starting' : sweepState || 'planned'}`} />
      </header>
      {sweepSupervisionUnknown && (
        <OperationStatus tone="info" title={t('run.sweepSupervisionTitle')} detail={t('run.sweepSupervisionDetail')} />
      )}
      <div className="sweep-controls">
        <div className="sweep-recipe" aria-label={t('run.sweepRecipe')}>
          <div className="sweep-recipe-step">
            <span>01</span>
            <div><strong>{t('run.sweepStep1')}</strong><small>{t('run.sweepStep1Desc')}</small></div>
          </div>
          <SweepParameterPicker
            base={active?.path ?? null}
            value={sweepParameter}
            disabled={safetyOperationActive}
            onChange={(nextParameter) => { setSweepParameter(nextParameter); resetSweepPlan(); }}
          />
          <div className="sweep-recipe-step">
            <span>02</span>
            <div><strong>{t('run.sweepStep2')}</strong><small>{t('run.sweepStep2Desc')}</small></div>
          </div>
          <SweepValueBuilder
            value={sweepValues}
            disabled={safetyOperationActive}
            onChange={(nextValues) => { setSweepValues(nextValues); resetSweepPlan(); }}
          />
          <div className="sweep-recipe-summary">
            <span>{t('run.studySize')}</span>
            <strong>{t('run.caseCount', { count: sweepCaseCount })}</strong>
            <small>{t('run.maxCases')}</small>
          </div>
        </div>
        <div className="sweep-actions">
          <Button variant="secondary" className="run-btn" onClick={doSweepPreview} disabled={safetyOperationActive || !runReady || !sweepSpec.trim()} busy={sweepPreviewing} busyLabel={t('run.preparing')}>{t('run.reviewCases', { count: sweepCaseCount })}</Button>
          <Button variant="primary" className="run-go" onClick={doSweepRun} disabled={safetyOperationActive || !runReady || !sweepPreview || !sweepSpec.trim()} busy={sweepStarting} busyLabel={t('run.startingBusy')}>{t('run.runSweep')}</Button>
          {sweepCancellable && <Button variant="quiet" className="stop" onClick={doSweepCancel} disabled={requestOperationActive && !sweepCancelling} busy={sweepCancelling} busyLabel={t('run.sweepCancelling')}>{t('run.stopSweep')}</Button>}
        </div>
      </div>

      {sweepPreview || sweepStatus ? (
        <Receipt
          title={sweepStatus ? sweepSupervisionUnknown ? `${t('run.sweepEvidence')} · ${t('run.sweepLastKnown')}` : t('run.sweepEvidence') : t('run.sweepPreviewTitle')}
          meta={t('run.caseCount', { count: (sweepStatus ?? sweepPreview)?.case_count ?? 0 })}
          className="sweep-receipt"
        >
          <RunSweepStatus preview={sweepPreview} status={sweepStatus} supervisionUnknown={sweepSupervisionUnknown} />
        </Receipt>
      ) : (
        <RunSweepStatus preview={sweepPreview} status={sweepStatus} supervisionUnknown={sweepSupervisionUnknown} />
      )}
    </section>
  );
}
