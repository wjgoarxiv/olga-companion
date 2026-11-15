import type { RunStatus } from './session';
import { basename } from './util';
import { useLocale } from './i18n/index.ts';
import type { TranslateFn } from './i18n/index.ts';
import { runStateLabel } from './runReason.ts';
import { runNextAction, runStopNotice, solverLogHighlights } from './runPresentation';
import { Button } from './ui/Button';
import { OperationStatus } from './ui/OperationStatus';
import { Receipt } from './ui/Receipt';
import { Table } from './ui/Table';

type RunFailurePanelProps = {
  readonly status: RunStatus;
  readonly historical?: boolean;
  readonly supervisionUnknown?: boolean;
  readonly onOpenResult?: (resultId: string) => void;
  /** Offered only where the screen would otherwise tell the user to press a button that is not there. */
  readonly onRetryContext?: () => void;
  readonly onDraftQuestion?: (prompt: string) => void;
  readonly contextLoading?: boolean;
};

const TERMINAL_RUN_STATES = new Set(['completed', 'failed', 'cancelled', 'timed_out']);

function bytesLabel(size: number, t: TranslateFn): string {
  if (size >= 1024 * 1024) {
    const mb = (size / (1024 * 1024)).toFixed(1);
    return t('saveas.bytesMB', { value: mb }) ?? `${mb} MB`;
  }
  const kb = Math.max(1, Math.round(size / 1024));
  return t('saveas.bytesKB', { value: kb }) ?? `${kb} KB`;
}

function actionSteps(action: string): string[] {
  return action
    .split(/\r?\n+|;\s+|(?<=[.!?])\s+(?=[A-Z0-9])/)
    .map((step) => step.replace(/^\s*\d+[.)]\s*/, '').trim())
    .filter(Boolean);
}

export function RunFailurePanel({ status, historical = false, supervisionUnknown = false, onOpenResult, onRetryContext, onDraftQuestion, contextLoading = false }: RunFailurePanelProps) {
  const { t } = useLocale();
  const failure = status.failure;
  const runtimeVersion = status.version ?? status.detection?.version;
  const runtimeKind = status.kind ?? status.detection?.kind;
  const candidateId = status.candidate_id ?? status.detection?.candidate_id;
  const hasRunEvidence = TERMINAL_RUN_STATES.has(status.state);
  const stopNotice = runStopNotice(status, t);
  const nextAction = runNextAction(status, supervisionUnknown, t);
  const lineageValue = supervisionUnknown
    ? t('run.lineageLastKnown')
    : status.lineage_status || (status.recovered_from_receipt ? t('run.lineageRecovered') : t('run.lineageCurrent'));
  const highlights = hasRunEvidence && status.state !== 'completed' && status.log_tail
    ? solverLogHighlights(status.log_tail)
    : null;

  return (
    <div className="run-status" data-run-source={historical ? 'history' : 'live'}>
      {historical && (
        <p className="run-history-note">
          <strong>{t('run.historyNote')}</strong> · {t('run.historyDetail')}
        </p>
      )}
      <div className={`run-terminal run-terminal-${status.state}`} role="status">
        <span className="run-terminal-primary">
          <span className="run-terminal-dot" aria-hidden="true" />
          <span><small>{t('run.processState')}</small><strong className="run-terminal-state">{runStateLabel(status.state, t)}</strong></span>
        </span>
        <span className="run-terminal-metrics">
          {status.exit_code != null && <span className="run-terminal-metric"><small>{t('run.exit')}</small><strong>{status.exit_code}</strong></span>}
          <span className="run-terminal-metric"><small>{t('run.elapsed')}</small><strong>{(status.elapsed_ms / 1000).toFixed(1)} s</strong></span>
          {supervisionUnknown && <span className="run-terminal-metric"><small>{t('run.evidence')}</small><strong>{t('run.lastKnown')}</strong></span>}
        </span>
      </div>
      {hasRunEvidence && (
        <Receipt title={t('run.receipt')} meta={`${status.run_id} · ${runStateLabel(status.state, t)}${supervisionUnknown ? ` · ${t('run.lastKnown')}` : ''}`} className="run-receipt-shell">
          <div className="run-receipt" aria-label={t('run.receiptAria')}>
            <span><strong>{t('run.receipt')}</strong><em title={status.run_id}>{status.run_id}</em></span>
            <span><strong>{t('run.sourceCase')}</strong><em title={basename(status.source_name || status.detection?.case_source || (t('run.unknownSource') ?? 'Unknown source'))}>{basename(status.source_name || status.detection?.case_source || (t('run.unknownSource') ?? 'Unknown source'))}</em></span>
            <span><strong>{t('run.runtime')}</strong><em title={t('run.runtimeFull', { version: runtimeVersion || t('run.versionUnknown'), kind: runtimeKind || t('run.launcher.unknown') })}>{t('run.runtimeFull', { version: runtimeVersion || t('run.versionUnknown'), kind: runtimeKind || t('run.launcher.unknown') })}</em></span>
            <span><strong>{t('run.validation')}</strong><em title={status.validation_valid === true ? t('run.pass') : status.validation_valid === false ? t('run.fail') : t('run.notRecorded')}>{status.validation_valid === true ? t('run.pass') : status.validation_valid === false ? t('run.fail') : t('run.notRecorded')}</em></span>
            <span><strong>{t('run.lineageOrigin')}</strong><em title={`${lineageValue}${candidateId ? ` · ${candidateId.slice(0, 12)}` : ''}`}>{lineageValue}{candidateId ? ` · ${candidateId.slice(0, 12)}` : ''}</em></span>
          </div>
        </Receipt>
      )}
      {status.state === 'recovery_unknown' && (
        <OperationStatus className="run-recovery" tone="info" title={t('run.recoveryUnknown')} detail={status.recovery || t('run.recoveryEmpty')} />
      )}
      {supervisionUnknown && (
        <OperationStatus className="run-recovery" tone="info" title={t('run.errSupervision')} detail={t('run.supervisionDetail')} action={onRetryContext ? <Button variant="secondary" onClick={onRetryContext} busy={contextLoading} busyLabel={t('run.retryBusy')}>{t('run.retryContext')}</Button> : undefined} />
      )}
      {stopNotice ? (
        <section className="run-failure" aria-label={stopNotice.title}>
          <strong>{stopNotice.title}</strong>
          <p>{stopNotice.detail}</p>
          {stopNotice.action && <p>{stopNotice.action}</p>}
        </section>
      ) : failure && (
        <section className="run-failure" aria-label={t('run.failureAria') ?? 'Run failure diagnosis'}>
          <strong>{failure.title}</strong>
          <p>{failure.detail}</p>
          <ol className="run-failure-steps" aria-label="Operator recovery steps">
            {actionSteps(failure.action).map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}
          </ol>
          {!failure.auto_retry_safe && <small>{t('run.autoRetryOff')}</small>}
        </section>
      )}
      {status.solver_findings && status.solver_findings.length > 0 && (
        <section className="run-failure" aria-label={t('run.solverAria')}>
          <strong>{t('run.solverAria')}</strong>
          <ul>
            {status.solver_findings.map((finding) => (
              <li key={`${finding.code}-${finding.line ?? 'none'}-${finding.time ?? 'none'}`}>
                <p><code>{finding.code}</code> {finding.message}</p>
                {finding.line != null && <p>{t('run.lineWord')} {finding.line}{finding.time != null ? ` · ${t('run.timeWord')} ${finding.time}` : ''}</p>}
                {finding.suggestion && (
                  <>
                    <p>{t('run.suggestionNote')}</p>
                    <p>{finding.suggestion}</p>
                    <Button variant="secondary" onClick={() => onDraftQuestion?.(t('run.askDraftPrompt', { code: finding.code, suggestion: finding.suggestion ?? '' }) ?? `실패한 실행의 ${finding.code} 진단을 설명해 주세요. 제안: ${finding.suggestion}. 사례 파일은 바꾸지 마세요.`)}>{t('run.askDraft')}</Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {highlights && (
        <section className="run-log-excerpt" aria-label={t('run.solverLogAria')}>
          <strong>{highlights.kind === 'fault' ? t('run.logFault') : t('run.logLast')}</strong>
          <pre>{highlights.lines.join('\n')}</pre>
        </section>
      )}
      {nextAction && <p className="run-next-action"><strong>{t('run.nextStep')}</strong> {nextAction}</p>}
      {hasRunEvidence && <section className="run-outputs" aria-label={t('run.outputsTitle')}>
        <div className="run-output-head">
          <strong>{t('run.outputsTitle')}</strong>
          <span>{t(status.outputs.length === 1 ? 'run.fileOne' : 'run.fileOther', { count: status.outputs.length })}</span>
        </div>
        {status.outputs.length > 0 ? (
          <Table
            ariaLabel={t('run.outputsTitle')}
            columns={[
              { key: 'file', header: t('run.outputFile') ?? 'File' },
              { key: 'open', header: t('run.outputOpen') ?? 'Open' },
            ]}
            rows={status.outputs.map((output) => ({
              file: (
                <span className="run-output-copy">
                  <span className="run-output-name"><span className="run-output-suffix">{output.suffix.replace(/^\./, '') || (t('run.fileWord') ?? 'file')}</span><strong>{output.name}</strong></span>
                  <small>{t('run.outputMeta', { size: bytesLabel(output.size, t), sha: output.sha256.slice(0, 12) }) ?? `${bytesLabel(output.size, t)} · SHA-256 ${output.sha256.slice(0, 12)}…`}</small>
                </span>
              ),
              open: output.suffix.toLowerCase() === '.tpl' && output.result_id ? (
                <Button variant="secondary" onClick={() => { if (output.result_id) onOpenResult?.(output.result_id); }}>{t('run.openTpl')}</Button>
              ) : null,
            }))}
          />
        ) : (
          <p>{t('run.noOutputs')}</p>
        )}
      </section>}
      {hasRunEvidence && status.log_tail && (
        <details className="run-log-details">
          <summary>{t('run.logTail', { count: status.log_tail.split(/\r?\n/u).length })}</summary>
          <pre className="run-log" aria-label={t('run.solverLogAria')}>{status.log_tail}</pre>
        </details>
      )}
    </div>
  );
}
