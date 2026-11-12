import { launcherKindLabel } from './runViewModel';
import { basename } from './util';
import { useLocale } from './i18n/index.ts';
import { formatRunReasonParts } from './runReason.ts';
import type { RunLifecycle } from './useRunLifecycle';
import type { RunViewModel } from './runViewModel';
import type { RunViewState } from './useRunViewState';
import { Button } from './ui/Button';
import { ActivityLoader } from './ui/ActivityLoader';
import { OperationStatus } from './ui/OperationStatus';
import { WorkbenchPrompt } from './WorkbenchPrompt';

/** Seven days: the sidecar and the Explorer broker refuse a longer run limit. */
export const RUN_LIMIT_MAX_HOURS = 168;

type RunViewOverviewProps = {
  readonly state: RunViewState;
  readonly lifecycle: RunLifecycle;
  readonly model: RunViewModel;
  readonly onOpenWorkspace: () => void;
};

export function RunViewOverview({ state, lifecycle, model, onOpenWorkspace }: RunViewOverviewProps) {
  const {
    active, activeLoaded, detect, selectedCandidateId, timeoutHours, contextUnavailable,
    error, errorRetriesContext, contextLoading, supervisionUnknown,
    sweepSupervisionUnknown, starting,
    setSelectedCandidateId, setTimeoutHours, setPreview, setStatus, setRunId, setStarting,
  } = state;
  const { retryRunContext, stopPolling } = lifecycle;
  const {
    caseLabel, selectionBlocked, runtimeCandidates, runReady,
    safetyOperationActive, activeOperation, monitoringUnknown,
  } = model;
  const { t } = useLocale();
  const status = state.status;
  const hasRecoveredRecord = status != null
    && (state.statusSource === 'history' || status.recovered_from_receipt === true);
  const title = contextUnavailable
    ? t('run.titleMissing')
    : !activeLoaded
      ? t('run.titleLoading')
      : active?.path
        ? t('run.titleReady')
        : t('run.titleNoCase');
  // Sentence/code split: the visible line never carries the raw reason
  // code; stale or unknown codes disclose in <details> only.
  const reasonParts = detect
    ? formatRunReasonParts(detect, t, { hasRecoveredRecord })
    : null;

  return (
    <>
      {/* With no active case the prompt below carries its own title; a second header only repeats it. */}
      {(contextUnavailable || !activeLoaded || active?.path) && (
        <header className="run-head">
          <div className="run-title-block">
            <span className="run-eyebrow">{t('nav.run')}</span>
            <span className="run-title" title={caseLabel}>{title}</span>
          </div>
        </header>
      )}

      {!contextUnavailable && detect && active?.path && (
        <section className={`run-detection ${selectionBlocked ? 'blocked' : runReady ? 'ready' : 'unavailable'}`} aria-label={t('run.detectionAria')} aria-live="polite">
          <div className="run-detection-summary">
            <strong>{selectionBlocked ? t('run.blocked') : runReady ? t('run.selectedEnv') : t('run.noEnv')}</strong>
            {reasonParts && (
              <>
                <p>{reasonParts.text}</p>
                {reasonParts.code && (
                  <details className="run-reason-code">
                    <summary>{t('run.reason.codeLabel')}</summary>
                    <code>{reasonParts.code}</code>
                  </details>
                )}
              </>
            )}
            {detect.exe && <small>{basename(detect.exe)}</small>}
            {runtimeCandidates.length > 0 && (
              <label className="run-runtime-field">
                <span>{t('run.runtimeField')}</span>
                <select
                  aria-label={t('run.runtimeField')}
                  value={selectedCandidateId}
                  disabled={safetyOperationActive}
                  onChange={(event) => {
                    stopPolling();
                    setSelectedCandidateId(event.target.value);
                    setPreview(null);
                    setStatus(null);
                    setRunId(null);
                    setStarting(false);
                  }}
                >
                  {runtimeCandidates.map((candidate) => (
                    <option key={candidate.candidate_id} value={candidate.candidate_id}>
                      OLGA {candidate.version || t('run.versionUnknown')} · {launcherKindLabel(candidate.kind, t)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="run-runtime-field run-limit-field">
              <span>{t('run.timeLimitField')}</span>
              <input
                type="number"
                inputMode="numeric"
                aria-label={t('run.timeLimitField')}
                aria-describedby="run-limit-hint"
                min={1}
                max={RUN_LIMIT_MAX_HOURS}
                step={1}
                value={timeoutHours}
                disabled={safetyOperationActive}
                onChange={(event) => {
                  const hours = Math.round(Number(event.target.value));
                  setTimeoutHours(Number.isFinite(hours) ? Math.min(RUN_LIMIT_MAX_HOURS, Math.max(1, hours)) : 1);
                  setPreview(null);
                }}
              />
              <small id="run-limit-hint">{t('run.timeLimitHint', { max: String(RUN_LIMIT_MAX_HOURS) })}</small>
            </label>
          </div>
          {(detect.evidence.length > 0 || detect.alternatives.length > 0) && (
            <div className="run-detection-evidence">
              {detect.evidence.length > 0 && (
                <details className="run-alternatives">
                  <summary>{t('run.evidenceSummary')}</summary>
                  <ul>
                    {detect.evidence.map((evidence, index) => (
                      <li key={`${evidence.source_type}-${evidence.version}-${index}`}>
                        <span>OLGA {evidence.version} · {evidence.source_type} · {evidence.strength}</span>
                        <small>{basename(evidence.path)}{t('run.evidenceCase', { file: basename(evidence.input_file) }) ?? ` · case ${basename(evidence.input_file)}`}</small>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {detect.alternatives.length > 0 && (
                <details className="run-alternatives">
                  <summary>{selectionBlocked ? t('run.altBlocked') : t('run.altOthers')}</summary>
                  <ul>
                    {detect.alternatives.map((alternative, index) => (
                      <li key={`${alternative.exe}-${index}`}>
                        <span>OLGA {alternative.version || t('run.versionUnknown')} · {launcherKindLabel(alternative.kind, t)}</span>
                        <small>{basename(alternative.exe)}</small>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </section>
      )}

      {!activeLoaded && (
        <div className="run-loading-state">
          <span className="run-eyebrow">{t('run.restoring')}</span>
          <ActivityLoader loadingLabel={t('run.readingCase')} />
        </div>
      )}

      {activeLoaded && !contextUnavailable && !active?.path && (
        <WorkbenchPrompt
          className="run-empty-state"
          kicker={t('run.emptyKicker')}
          title={t('run.emptyTitle')}
          description={t('run.emptyDesc')}
          contextLabel={t('run.emptyContext')}
          contextValue={t('run.emptyValue')}
          contextDetail={t('run.emptyDetail')}
        >
          <div className="workbench-prompt-footer">
            <Button variant="primary" className="run-btn" onClick={onOpenWorkspace}>{t('run.openWorkspace')}</Button>
            <span className="workbench-prompt-note">{t('run.emptyNote')}</span>
          </div>
        </WorkbenchPrompt>
      )}

      {activeOperation && <OperationStatus className="run-operation-status" tone="busy" title={activeOperation} />}

      {error && <OperationStatus
        className="run-operation-status"
        tone={monitoringUnknown ? 'info' : 'error'}
        title={supervisionUnknown ? t('run.errSupervision') : sweepSupervisionUnknown ? t('run.errSweepSupervision') : errorRetriesContext ? t('run.errContext') : t('run.errAction')}
        detail={error}
        action={errorRetriesContext ? (
          <Button variant="secondary" onClick={retryRunContext} busy={contextLoading} busyLabel={t('run.retryBusy')}>{t('run.retryContext')}</Button>
        ) : undefined}
      />}
    </>
  );
}
