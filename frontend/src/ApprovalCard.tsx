import { Fragment, useEffect, useRef, useState } from 'react';
import { resolveApprovalCardLifecycle } from './approvalActionLifecycle';
import { APPROVAL_EXPIRED_SENTENCE, describeApprovalExpiry } from './approvalExpiry.mjs';
import PlanSteps from './PlanSteps';
import { PLAN_ACTION, planError, planOutcome, planStepRows } from './planApproval.mjs';
import { lifecycleLabelKey, useLocale } from './i18n/index.ts';
import type { ToolLifecycleState } from './approvalActionLifecycle';
import type { ApprovalRequest } from './types';
import { basename } from './util';
import { Button } from './ui/Button';
import { OperationStatus } from './ui/OperationStatus';

/** Ids and hashes stay as technical rows; every other server field reads as plain text. */
const TECHNICAL_FIELD_KEYS: ReadonlySet<string> = new Set(['plan_id', 'run_id', 'sweep_id']);

function isUsableFocusTarget(value: Element | null): value is HTMLElement {
  return typeof HTMLElement !== 'undefined'
    && value instanceof HTMLElement
    && value !== document.body
    && value.isConnected
    && !value.matches(':disabled, [aria-disabled="true"]')
    && value.tabIndex >= 0;
}

function fallbackFocusTarget(): HTMLElement | null {
  if (typeof document === 'undefined') return null;
  const chatInput = document.querySelector('[data-testid="chat-input"]');
  if (isUsableFocusTarget(chatInput)) return chatInput;

  // Stable fallback order: composer input first, then another enabled chat control.
  const chatControls = document.querySelectorAll<HTMLElement>('.chat button, .chat a[href], .chat [tabindex]');
  return Array.from(chatControls).find((control) => !control.closest('.approval-card') && isUsableFocusTarget(control)) ?? null;
}

/** The one loud moment by design: a human approving a real side effect. The card
 *  shows the exact pinned selection or plan and mints a token only on click.
 *  Approval is a human-only act — the agent cannot produce this token. */
export default function ApprovalCard({
  request,
  onApprove,
  onRecover,
  onReject,
  detail,
  lifecycle,
  pending,
  recoverable = false,
  resolved,
  resolution,
  result,
}: {
  request: ApprovalRequest;
  onApprove: (request: ApprovalRequest) => void;
  onRecover: (request: ApprovalRequest) => void;
  onReject: (request: ApprovalRequest) => void;
  readonly detail?: string;
  readonly lifecycle?: ToolLifecycleState;
  pending: boolean;
  readonly recoverable?: boolean;
  readonly resolved: boolean;
  readonly resolution?: 'context-expired' | 'rejected';
  readonly result?: Record<string, unknown>;
}) {
  const approveButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const focusRestoredRef = useRef(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  // Purely visual resolution state: the request itself fires synchronously in
  // the click handler below. This only drives the wipe/stamp/collapse CSS.
  const [visualResolution, setVisualResolution] = useState<'approved' | 'rejected' | null>(null);
  // Validity window observed at mount; the countdown bar drains the real
  // remaining time against it.
  const [windowMs] = useState(() => typeof request.expires_at === 'number'
    ? Math.max(0, request.expires_at * 1000 - Date.now())
    : 0);
  const { t } = useLocale();

  useEffect(() => {
    const expiresAt = request.expires_at;
    if (typeof expiresAt !== 'number' || resolved) return undefined;
    const tick = () => setNowMs(Date.now());
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [request.expires_at, resolved]);

  const expiry = describeApprovalExpiry(request.expires_at, nowMs);

  function restoreFocus() {
    if (focusRestoredRef.current) return;
    const target = isUsableFocusTarget(previousFocusRef.current) ? previousFocusRef.current : fallbackFocusTarget();
    if (!target) return;
    target.focus();
    focusRestoredRef.current = true;
  }

  useEffect(() => {
    const active = typeof document === 'undefined' ? null : document.activeElement;
    previousFocusRef.current = isUsableFocusTarget(active) ? active : null;
    focusRestoredRef.current = false;
    return () => restoreFocus();
  }, []);

  useEffect(() => {
    if (resolved) restoreFocus();
    if (!pending && !resolved && isUsableFocusTarget(approveButtonRef.current)) {
      approveButtonRef.current.focus();
    }
  }, [pending, resolved]);

  const isPlan = request.name === PLAN_ACTION;
  const planRows = isPlan ? planStepRows(request.display, result) : [];
  const outcome = isPlan ? planOutcome(result) : null;
  // A plan the server reviewed no step of is never approvable.
  const planDisplayReady = !isPlan || planRows.length > 0;
  const isSweep = request.name === 'sweep_execute';
  const isPublish = request.name === 'case_publish';
  const isRun = request.name === 'run_execute';
  const reviewed = request.display ?? {};
  const runtimeVersion = isRun ? String(reviewed.runtime_version ?? '') : '';
  const unverifiedVersion = isRun && (!runtimeVersion || !runtimeVersion.startsWith('2022.1'));
  const displayWarnings: readonly string[] = Array.isArray(reviewed.warnings)
    ? reviewed.warnings.filter((entry: unknown): entry is string => typeof entry === 'string' && entry.length > 0)
    : [];
  const reviewedInputs = Array.isArray(reviewed.inputs) ? reviewed.inputs : [];
  const inputGroups: ReadonlyArray<{ readonly group: string; readonly items: ReadonlyArray<{ readonly name: string; readonly value: string; readonly unit: string }> }> = (() => {
    const groups: Array<{ group: string; items: Array<{ name: string; value: string; unit: string }> }> = [];
    for (const entry of reviewedInputs) {
      if (typeof entry !== 'object' || entry === null) continue;
      const record = entry as Record<string, unknown>;
      if (typeof record.group !== 'string' || typeof record.name !== 'string' || typeof record.value !== 'string') continue;
      const unit = typeof record.unit === 'string' ? record.unit : '';
      let group = groups.find((candidate) => candidate.group === record.group);
      if (!group) {
        group = { group: record.group, items: [] };
        groups.push(group);
      }
      group.items.push({ name: record.name, value: record.value, unit });
    }
    return groups;
  })();
  const reviewedFields: ReadonlyArray<{ readonly key: string; readonly value: string; readonly unit: string }> = (Array.isArray(reviewed.fields) ? reviewed.fields : []).flatMap((entry: unknown) => {
    if (typeof entry !== 'object' || entry === null) return [];
    const record = entry as Record<string, unknown>;
    if (typeof record.key !== 'string' || typeof record.value !== 'string') return [];
    return [{ key: record.key, value: record.value, unit: typeof record.unit === 'string' ? record.unit : '' }];
  });
  const hasFields = reviewedFields.length > 0;
  const headKey = `approval.head.${request.name}`;
  const headLabel = t(headKey);
  const isWrite = request.name === 'fluids_draft_mfl' || request.name === 'fluids_generate_tab' || request.name === 'fluids_starter_tab' || request.name === 'genkey_save';
  const isOpen = request.name === 'multiflash_open';
  const isCancel = request.name === 'run_cancel' || request.name === 'sweep_cancel';
  const source = String(isRun ? reviewed.case ?? '' : request.args.source ?? '');
  const sweepId = hasFields ? '' : String(request.args.sweep_id ?? '');
  const pinnedId = String(isRun ? reviewed.selection_id ?? '' : isSweep && !hasFields ? request.args.plan_id ?? '' : '');
  const timeout = typeof reviewed.timeout_s === 'number' ? String(reviewed.timeout_s) : '';
  const sourceHash = isRun
    ? String(reviewed.source_sha256 ?? '')
    : typeof request.args.source_hash === 'string' ? request.args.source_hash : '';
  const runtime = isRun ? String(reviewed.runtime_id ?? '') : '';
  const executable = isRun ? basename(String(reviewed.executable ?? '')) : '';
  const outputTarget = isRun ? String(reviewed.output_target ?? '') : '';
  const runDisplayReady = !isRun || Boolean(
    reviewed.selection_id && reviewed.runtime_id && reviewed.executable
    && reviewed.output_target && reviewed.source_sha256,
  );
  const transactionId = typeof request.args.transaction_id === 'string' ? request.args.transaction_id : '';
  const compiledHash = typeof request.args.compiled_hash === 'string' ? request.args.compiled_hash : '';
  const destination = typeof request.args.destination_rel === 'string' ? request.args.destination_rel : '';
  const contextGeneration = typeof request.args.context_generation === 'number'
    ? String(request.args.context_generation) : '';
  // Sticky what-where line: the action bar is position-sticky, so this summary
  // stays co-visible with the buttons even when the evidence list scrolls away.
  const destinationFile = destination ? basename(destination) : '';
  const hashShort = compiledHash ? compiledHash.slice(0, 12) : '';
  const stickySummary = isPublish && destinationFile ? (
    <>{t('approval.stickyTarget')} <strong>{destinationFile}</strong>{hashShort && <> · {hashShort}</>} · {t('approval.stickyAsIs')}</>
  ) : null;
  const cardLifecycle = resolveApprovalCardLifecycle({ lifecycle, resolved, resolution });
  if (resolved && detail === APPROVAL_EXPIRED_SENTENCE) {
    return (
      <OperationStatus
        className="approval-resolved"
        tone="error"
        title={t('approval.expiredTitle')}
        detail={t('approval.expiredLine')}
      />
    );
  }
  if (resolved && isPlan && outcome !== null) {
    const ranClean = outcome === 'completed' || outcome === 'started';
    // With no step row to carry the reason, say why the whole sequence stopped.
    const stopReason = outcome === 'stopped' && !planRows.some((row) => row.error) ? planError(result) : '';
    return (
      <div className="approval-resolved-plan">
        <OperationStatus
          className="approval-resolved"
          tone={ranClean ? 'success' : 'error'}
          title={t(outcome === 'completed' ? 'approval.plan.resolvedDone' : outcome === 'started' ? 'approval.plan.resolvedStarted' : outcome === 'stopped' ? 'approval.plan.resolvedStopped' : 'approval.plan.resolvedUncertain')}
          detail={outcome === 'stopped' ? [t('approval.plan.stoppedNote'), stopReason].filter(Boolean).join(' ') : undefined}
        />
        <PlanSteps rows={planRows.map((row) => (row.state === 'waiting' ? { ...row, state: 'not_run' } : row))} />
      </div>
    );
  }
  if (resolved && lifecycle === 'failed' && detail && resolution !== 'context-expired') {
    return (
      <OperationStatus
        className="approval-resolved"
        tone="error"
        title={isPublish ? t('approval.publishRefused') : t('approval.runRefused')}
        detail={detail}
      />
    );
  }
  if (resolved) {
    return (
      <OperationStatus
        className="approval-resolved"
        tone="info"
        title={t('approval.resolvedTitle')}
        detail={resolution === 'context-expired'
          ? t('approval.resolvedContextExpired', { name: request.name })
          : resolution === 'rejected'
            ? t('approval.resolvedRejected', { name: request.name })
            : detail || t('approval.resolvedClosed', { name: request.name })}
      />
    );
  }
  const remainingMs = typeof request.expires_at === 'number'
    ? Math.max(0, request.expires_at * 1000 - nowMs)
    : null;
  const countdownPct = remainingMs != null && windowMs > 0
    ? Math.max(0, Math.min(100, (remainingMs / windowMs) * 100))
    : null;
  return (
    <div className="approval-card" role="alertdialog" aria-label={t('approval.title')} data-resolution={visualResolution ?? undefined}>
      <div className="approval-collapse"><div className="approval-collapse-body">
      <p className="approval-head">{t('approval.title')} — {isPublish ? t('approval.headPublish') : headLabel === headKey ? request.name : headLabel}</p>
      {cardLifecycle !== 'awaiting-approval' && (
        <OperationStatus
          className="approval-lifecycle"
          tone={cardLifecycle === 'uncertain' ? 'error' : 'busy'}
          title={t(lifecycleLabelKey(cardLifecycle))}
          detail={detail || (isPlan && outcome === 'uncertain'
            ? t('approval.plan.resolvedUncertain')
            : cardLifecycle === 'finalizing'
              ? t('approval.lifecycleFinalizing')
              : t('approval.lifecycleWorking'))}
        />
      )}
      <dl>
        {reviewedFields.map((field, index) => (
          <Fragment key={`${field.key}-${index}`}>
            <dt>{t(`approval.field.${field.key}`)}</dt>
            <dd className={TECHNICAL_FIELD_KEYS.has(field.key) ? 'evidence-value-technical' : undefined}>
              {field.value}{field.unit ? ` ${field.unit}` : ''}
            </dd>
          </Fragment>
        ))}
        {(isSweep ? sweepId : source) && <><dt>{isSweep ? t('approval.fieldSweep') : t('approval.fieldCase')}</dt><dd><span className="approval-file">{isSweep ? sweepId : basename(source)}</span></dd></>}
        {isPublish && <>
          <dt>{t('approval.fieldTransaction')}</dt><dd className="evidence-value-technical">{transactionId}</dd>
          <dt>{t('approval.fieldCompiledHash')}</dt><dd className="evidence-value-technical">{compiledHash}</dd>
          <dt>{t('approval.fieldDestination')}</dt><dd className="evidence-value-technical">{destination}</dd>
          <dt>{t('approval.fieldGeneration')}</dt><dd className="evidence-value-technical">{contextGeneration}</dd>
        </>}
        {pinnedId && (
          <>
            <dt>{isSweep ? t('approval.fieldPlan') : t('approval.fieldSelection')}</dt>
            <dd><span className="approval-file">{pinnedId}</span></dd>
          </>
        )}
        {runtime && <><dt>{t('approval.fieldRuntime')}</dt><dd className="evidence-value-technical">{runtime}</dd></>}
        {executable && <><dt>{t('approval.fieldExecutable')}</dt><dd className="evidence-value-technical">{executable}</dd></>}
        {outputTarget && <><dt>{t('approval.fieldOutput')}</dt><dd className="evidence-value-technical">{outputTarget}</dd></>}
        {sourceHash && <><dt>{t('approval.fieldSourceHash')}</dt><dd className="evidence-value-technical">{sourceHash}</dd></>}
        {!isSweep && !isPublish && timeout && (
          <>
            <dt>{t('approval.fieldTimeout')}</dt>
            <dd>{t('approval.timeoutSeconds', { timeout })}</dd>
          </>
        )}
      </dl>
      {isPlan && <PlanSteps rows={planRows} />}
      {expiry.expired
        ? <p className="approval-expiry">{t('approval.expiredLine')}</p>
        : expiry.time
          ? <p className="approval-expiry">{t('approval.validUntil', { time: expiry.time })}{countdownPct != null && <span className="approval-countdown" aria-hidden="true"><span style={{ width: `${countdownPct}%` }} /></span>}</p>
          : null}
      <p className="hint">
        {!planDisplayReady
          ? t('approval.hintPlanNoDisplay')
          : !runDisplayReady
          ? t('approval.hintNoDisplay')
          : isPlan ? t('approval.hintPlan')
            : isPublish ? t('approval.hintPublish')
            : isWrite ? t('approval.hintWrite')
              : isOpen ? t('approval.hintOpen')
                : isCancel ? t('approval.hintCancel')
                  : t('approval.hintRun')} {t('approval.hintHuman')}
      </p>
      {inputGroups.length > 0 && (
        <section className="approval-inputs" aria-label={t('approval.inputsTitle')}>
          <p className="approval-inputs-title"><strong>{t('approval.inputsTitle')}</strong><span>{t('approval.inputsNote')}</span></p>
          {inputGroups.map((group) => (
            <div key={group.group} className="approval-input-group">
              <p className="approval-input-group-title">{group.group}</p>
              <dl>
                {group.items.map((item) => (
                  <div key={item.name} className="approval-input-row">
                    <dt>{item.name}</dt>
                    <dd>{item.value}{item.unit ? ` ${item.unit}` : ''}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </section>
      )}
      {displayWarnings.length > 0 && (
        <section className="approval-warnings" aria-label={t('approval.warningsTitle')}>
          <p className="approval-warnings-title"><strong>{t('approval.warningsTitle')}</strong></p>
          {displayWarnings.map((warning, index) => (
            <p key={index} className="evidence-safety">{warning}</p>
          ))}
        </section>
      )}
      {unverifiedVersion && (
        <p className="evidence-safety">{t('approval.unverifiedVersion')}</p>
      )}

      <div className="approval-actions">
        {stickySummary && <p className="approval-sticky-summary">{stickySummary}</p>}
        {recoverable ? (
          <Button ref={approveButtonRef} variant="primary" className="approve" onClick={() => onRecover(request)} disabled={pending}>
            {t('approval.retryContinuation')}
          </Button>
        ) : (
          <>
                <Button ref={approveButtonRef} variant="primary" className="approve" onClick={() => { onApprove(request); setVisualResolution('approved'); }} disabled={pending || expiry.expired || cardLifecycle !== 'awaiting-approval' || !runDisplayReady || !planDisplayReady}>
                  {isPlan ? t('approval.approvePlan')
                    : isPublish ? t('approval.approvePublish')
                    : isWrite ? t('approval.approveWrite')
                      : isOpen ? t('approval.approveOpen')
                        : isCancel ? t('approval.approveCancel')
                          : t('approval.approveRun')}
            </Button>
            <Button variant="secondary" className="reject" onClick={() => { onReject(request); setVisualResolution('rejected'); }} disabled={pending || cardLifecycle !== 'awaiting-approval'}>
              {t('approval.reject')}
            </Button>
          </>
        )}
      </div>
      </div></div>
      {visualResolution === 'approved' && <span className="approval-stamp" aria-hidden="true">{t('approval.stampApproved')}</span>}
    </div>
  );
}
