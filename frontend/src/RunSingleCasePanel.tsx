import { useEffect, useRef } from 'react';
import { RunProgress } from './RunProgress';
import { RunStatePill } from './RunStatePill';
import { approveBlockedReason, liveRunStatus } from './runPresentation';
import type { RunActions } from './useRunActions';
import type { RunViewModel } from './runViewModel';
import type { RunViewState } from './useRunViewState';
import { Button } from './ui/Button';
import { useLocale } from './i18n/index.ts';
import { runStateLabel } from './runReason.ts';
import { Receipt } from './ui/Receipt';
import { getCaseProblemsSnapshot } from './shell/caseProblems';

/** Collapse-request contract for the shell: dispatched when a valid,
    error-free preview lands so the bottom Problems panel can yield the
    viewport to the receipt. The shell listener that consumes this event
    is a later wave; the name and guard semantics are pinned here and in
    run-preview-visibility.test.mjs. */
export const COLLAPSE_PROBLEMS_EVENT = 'olga:collapse-problems-panel' as const;

type RunSingleCasePanelProps = {
  readonly state: RunViewState;
  readonly actions: RunActions;
  readonly model: RunViewModel;
};

export function RunSingleCasePanel({ state, actions, model }: RunSingleCasePanelProps) {
  const { t } = useLocale();
  const {
    status, statusSource, supervisionUnknown, starting, previewing, preview,
    cancelling, usedSelectionId,
  } = state;
  const { doPreview, doRun, doCancel } = actions;
  const {
    safetyOperationActive, runReady, runCancellable, requestOperationActive,
    previewLauncherText,
  } = model;
  const progressRef = useRef<HTMLDivElement | null>(null);
  // A receipt restored from an earlier session is history, not this view's run state.
  const liveStatus = liveRunStatus(status, statusSource);
  const blockedReason = approveBlockedReason({ operationActive: safetyOperationActive, runReady, preview, usedSelectionId, t });
  const stateKey = supervisionUnknown ? 'last_known' : starting ? 'starting' : liveStatus?.state || 'ready';
  const stateClass = supervisionUnknown ? 'planned' : starting ? 'starting' : liveStatus?.state || 'planned';

  useEffect(() => {
    if (!liveStatus || !window.matchMedia('(max-width: 760px)').matches) return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    progressRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
  }, [starting, liveStatus?.state]);

  const panelRef = useRef<HTMLElement | null>(null);
  const prevPreviewRef = useRef<typeof preview | null>(null);
  // M11: when a new preview lands, bring its receipt into view inside the
  // run-body scroller. Collapse is request-only and strictly guarded: a
  // valid preview with zero case-problem error rows. Anything else keeps
  // the errors (and the receipt) visible. Never approves or starts.
  useEffect(() => {
    const prev = prevPreviewRef.current;
    prevPreviewRef.current = preview ?? null;
    if (preview == null || prev === preview) return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    panelRef.current?.querySelector('.run-preview-card')?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest' });
    const errorRows = getCaseProblemsSnapshot().filter((problem) => problem.severity === 'error');
    if (preview.validation.valid && errorRows.length === 0) {
      window.dispatchEvent(new CustomEvent(COLLAPSE_PROBLEMS_EVENT));
    }
  }, [preview]);

  return (
    <section ref={panelRef} className="run-panel" aria-label={t('run.panelSingleAria')}>
      <header className="run-panel-head">
        <span>{t('run.singleCase')}</span>
        <RunStatePill statusLabel={runStateLabel(stateKey, t)} statusClass={`run-${stateClass}`} />
      </header>
      <div className="run-actions">
        <Button variant="secondary" className="run-btn" onClick={doPreview} disabled={safetyOperationActive || !runReady} busy={previewing} busyLabel={t('run.preparing')}>{t('approval.previewCommand')}</Button>
        <Button variant="primary" className="run-go" onClick={doRun} disabled={blockedReason !== ''} aria-describedby={blockedReason && !starting ? 'run-approve-hint' : undefined} busy={starting} busyLabel={t('run.startingBusy')}>{t('approval.approveRun')}</Button>
        {runCancellable && <Button variant="quiet" className="stop" onClick={doCancel} disabled={status?.cancel_requested || (requestOperationActive && !cancelling)} busy={cancelling} busyLabel={t('run.cancelling')}>{status?.cancel_requested ? t('run.cancelRequested') : t('run.stopRun')}</Button>}
      </div>

      {blockedReason && !starting && <p id="run-approve-hint" className="run-hint">{blockedReason}</p>}
      {!blockedReason && !starting && <p className="run-hint">{t('run.approveHintDefault')}</p>}

      {liveStatus && (
        <div ref={progressRef} className="run-progress-anchor" data-testid="run-progress-anchor" data-inflight={stateClass === 'running' || stateClass === 'starting' ? 'true' : undefined}>
          <RunProgress progress={liveStatus.solver_progress} cancelRequested={liveStatus.cancel_requested} supervisionUnknown={supervisionUnknown} />
        </div>
      )}

      {preview != null && (
        <Receipt title={t('run.previewTitle')} meta={previewLauncherText ?? undefined} className="run-preview-card run-receipt">
          <div className="run-preview-facts">
            <span><strong>{t('run.validator')}</strong><em className={preview.validation.valid ? 'pass' : 'fail'}>{preview.validation.valid ? t('run.pass') : t('run.fail')}</em></span>
            <span><strong>{t('run.sandbox')}</strong><em>{t('run.sandboxDetail')}</em></span>
            <span><strong>{t('run.ownerSource')}</strong><em>{t('run.ownerDetail')}</em></span>
            <span><strong>{t('run.timeLimit')}</strong><em>{t('run.timeLimitHours', { hours: String(Math.round(preview.timeout_s / 360) / 10) })}</em></span>
          </div>
          <pre className="run-preview" title={preview.display_command.map((part) => String(part)).join(' ')}>{preview.display_command.map((part) => String(part)).join(' ')}</pre>
        </Receipt>
      )}
    </section>
  );
}
