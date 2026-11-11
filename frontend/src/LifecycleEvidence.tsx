import { useEffect, useState } from 'react';
import CaseSpecEvidence from './CaseSpecEvidence';
import { useLocale, type TranslateFn } from './i18n/index.ts';
import type { I18nKey } from './i18n/ko.ts';
import { runStatus } from './runApi';
import { startRunFinishPoll } from './runFinishPoll';
import { getRunFinish, publishRunFinish, useRunFinish, type RunFinishState } from './runFinishStore';

type Result = Record<string, unknown>;

const LIFECYCLE_TOOLS = new Set([
  'simulation_setup',
  'run_patrol',
  'case_edit_plan',
  'case_publish',
  'case_spec_validate',
  'case_spec_compile',
]);

export function isLifecycleEvidence(name: string): boolean {
  return LIFECYCLE_TOOLS.has(name);
}

function text(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function boundedValue(value: unknown): string {
  const scalar = text(value);
  if (scalar !== null) return scalar;
  if (value === null) return 'null';
  try {
    return JSON.stringify(value).slice(0, 240);
  } catch {
    return '[unavailable]';
  }
}

function record(value: unknown): Result | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Result : null;
}

function auditRows(result: Result, keys: readonly string[]) {
  return keys.flatMap((key) => {
    const value = text(result[key]);
    return value ? [[key, value] as const] : [];
  });
}

function Audit({ rows }: { readonly rows: readonly (readonly [string, string])[] }) {
  const { t } = useLocale();
  if (!rows.length) return null;
  return (
    <details className="evidence-audit">
      <summary>{t('lifecycle.audit')}</summary>
      <dl>
        {rows.map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll('_', ' ')}</dt>
            <dd className="evidence-value-technical">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function Outcome({ good, title, detail }: { readonly good: boolean; readonly title: string; readonly detail: string }) {
  return (
    <header className={`evidence-outcome ${good ? 'is-good' : 'is-attention'}`}>
      <div>
        <strong>{title}</strong>
        <p className="evidence-prose">{detail}</p>
      </div>
    </header>
  );
}

function SetupEvidence({ result }: { readonly result: Result }) {
  const { t } = useLocale();
  const ready = result.ready === true;
  const reason = text(result.reason);
  return (
    <div className="evidence-lifecycle">
      <Outcome
        good={ready}
        title={ready ? t('lifecycle.setupReady') ?? 'Simulation setup ready' : t('lifecycle.setupAttention') ?? 'Setup requires attention'}
        detail={ready
          ? t('lifecycle.setupReadyDetail') ?? 'The selected case, runtime, integration settings, and output contract passed preflight.'
          : reason ? t('lifecycle.setupStoppedDetail', { reason: reason.replaceAll('_', ' ') }) ?? `Preflight stopped: ${reason.replaceAll('_', ' ')}.` : t('lifecycle.setupNoSelection') ?? 'Preflight did not produce a runnable selection.'}
      />
      <Audit rows={auditRows(result, ['selection_id', 'run_input_sha256', 'setup_hash', 'runtime_id', 'candidate_id', 'context_generation'])} />
    </div>
  );
}

const PATROL_METRIC_LABEL_KEYS: Record<string, I18nKey> = {
  simulation_time_s: 'lifecycle.patrolMetric.simulationTime',
  step: 'lifecycle.patrolMetric.step',
  adaptive_total_steps: 'lifecycle.patrolMetric.adaptiveTotalSteps',
  phase: 'lifecycle.patrolMetric.phase',
  liveness: 'lifecycle.patrolMetric.liveness',
};

const PATROL_PHASE_LABEL_KEYS: Record<string, I18nKey> = {
  running: 'lifecycle.phase.running',
  finalizing: 'lifecycle.phase.finalizing',
  terminal: 'lifecycle.phase.terminal',
  supervision_unknown: 'lifecycle.phase.supervisionUnknown',
  indeterminate: 'lifecycle.phase.indeterminate',
};

const PATROL_LIVENESS_LABEL_KEYS: Record<string, I18nKey> = {
  supervised: 'lifecycle.liveness.supervised',
  terminal: 'lifecycle.liveness.terminal',
  supervision_unknown: 'lifecycle.liveness.supervisionUnknown',
  indeterminate: 'lifecycle.liveness.indeterminate',
};

const LATE_FINISH_DETAIL_KEYS: Record<RunFinishState, I18nKey> = {
  completed: 'lifecycle.patrolLateFinish.completed',
  failed: 'lifecycle.patrolLateFinish.failed',
  cancelled: 'lifecycle.patrolLateFinish.cancelled',
  timed_out: 'lifecycle.patrolLateFinish.timed_out',
};

function patrolMetricRows(
  latest: Result,
  t: TranslateFn,
  finished: boolean,
): readonly (readonly [key: string, label: string, value: string])[] {
  return (['simulation_time_s', 'step', 'adaptive_total_steps', 'phase', 'liveness'] as const).flatMap((key) => {
    const raw = text(latest[key]);
    if (!raw) return [];
    const labelKey = PATROL_METRIC_LABEL_KEYS[key];
    const label = labelKey ? t(labelKey) : key;
    if (finished && raw === 'indeterminate' && (key === 'phase' || key === 'liveness')) {
      const shown = key === 'phase' ? t('lifecycle.phase.terminal') : t('run.live.exited');
      return [[key, label, shown] as const];
    }
    const table = key === 'phase' ? PATROL_PHASE_LABEL_KEYS : key === 'liveness' ? PATROL_LIVENESS_LABEL_KEYS : null;
    return [[key, label, table?.[raw] ? t(table[raw] as I18nKey) : raw] as const];
  });
}

function PatrolEvidence({ result }: { readonly result: Result }) {
  const { t } = useLocale();
  const state = text(result.state) ?? 'unknown';
  const terminal = result.terminal === true;
  const runId = text(result.run_id);
  // A card whose patrol stopped early still follows its run to the end. It
  // reads the finish store first (the opener publishes every terminal state
  // there); only when the store holds nothing does it start the bounded
  // follow-up poll, which stops on unmount.
  const storedFinish = useRunFinish(!terminal && runId ? runId : null);
  const [polled, setPolled] = useState<RunFinishState | 'unknown' | null>(null);
  useEffect(() => {
    if (terminal || !runId) return;
    if (getRunFinish(runId) !== null) return;
    const stop = startRunFinishPoll(
      runId,
      { getFinish: getRunFinish, pollStatus: runStatus, publishFinish: publishRunFinish },
      { onTerminal: (finish) => setPolled(finish), onUnknown: () => setPolled('unknown') },
    );
    return () => {
      stop();
    };
  }, [terminal, runId]);
  const polledFinish = polled === 'unknown' ? null : polled;
  const finish = terminal ? null : (storedFinish ?? polledFinish);
  const unknown = !terminal && storedFinish === null && polled === 'unknown';
  const shownState = finish ?? state;
  const resolved = terminal || finish !== null;
  const runStateLabel = t(`run.state.${shownState}` as I18nKey);
  const observations = Array.isArray(result.observations) ? result.observations : [];
  const latest = record(observations[observations.length - 1]);
  const vendorPercent = typeof latest?.vendor_percent === 'number' && Number.isFinite(latest.vendor_percent)
    ? Math.max(0, Math.min(100, latest.vendor_percent))
    : null;
  const diagnosis = record(result.diagnosis);
  const proposal = record(result.proposal);
  const requiresFreshApproval = proposal?.requires_fresh_approval === true;
  return (
    <div className="evidence-lifecycle">
      <Outcome
        good={shownState === 'completed'}
        title={unknown
          ? t('lifecycle.patrolUnknown') ?? 'Run state unknown'
          : !resolved
            ? t('lifecycle.patrolObserved') ?? 'Run still going'
            : shownState === 'completed'
              ? t('lifecycle.patrolDone') ?? 'Run completed'
              : t('lifecycle.patrolState', { state: runStateLabel }) ?? `Run ${shownState}`}
        detail={terminal
          ? t('lifecycle.patrolTerminalDetail') ?? 'The terminal state comes from the durable runner receipt.'
          : finish !== null
            ? t(LATE_FINISH_DETAIL_KEYS[finish]) ?? t('lifecycle.patrolLateFinishDetail') ?? 'The run has since finished; the state above is its terminal state.'
            : unknown
              ? t('lifecycle.patrolUnknownDetail') ?? 'The run stopped in a state this app does not recognize. Follow it in the Run view.'
              : t('lifecycle.patrolBoundedDetail') ?? 'The chat stopped watching this run, but the run keeps going.'}
      />
      {vendorPercent !== null && (
        <div className="evidence-progress">
          <div><span>{finish !== null || unknown ? t('lifecycle.vendorProgressLastSeen') ?? 'Vendor progress (last seen)' : t('lifecycle.vendorProgress') ?? 'Vendor progress'}</span><strong>{vendorPercent.toFixed(1)}%</strong></div>
          <progress value={vendorPercent} max={100}>{vendorPercent}%</progress>
        </div>
      )}
      {latest && (
        <dl className="evidence-metrics">
          {patrolMetricRows(latest, t, resolved).map(([key, label, shown]) => (
            <div key={key}><dt>{label}</dt><dd>{shown}</dd></div>
          ))}
        </dl>
      )}
      {diagnosis && <p className="evidence-prose">{t('lifecycle.diagnosis', { reason: text(diagnosis.reason) ?? text(diagnosis.summary) ?? t('lifecycle.diagnosisFallback') ?? 'Review the bounded diagnostic evidence.' }) ?? `Diagnosis: ${text(diagnosis.reason) ?? text(diagnosis.summary) ?? 'Review the bounded diagnostic evidence.'}`}</p>}
      {proposal && (
        <p className="evidence-safety">
          {t('lifecycle.proposalReviewOnly') ?? 'Proposed change is review-only. requires_fresh_approval:'} <strong>{requiresFreshApproval ? 'true' : 'false'}</strong>
        </p>
      )}
      <Audit rows={auditRows(result, ['state', 'poll_count', 'elapsed_ms', 'recovered_from_receipt'])} />
    </div>
  );
}

function EditPlanEvidence({ result }: { readonly result: Result }) {
  const { t } = useLocale();
  const publishable = result.publishable === true || result.ok === true;
  const semanticDiff = Array.isArray(result.semantic_diff) ? result.semantic_diff : [];
  const textDiff = Array.isArray(result.text_diff) ? result.text_diff : [];
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const failedStep = text(result.failed_step);
  return (
    <div className="evidence-lifecycle">
      <Outcome
        good={publishable}
        title={publishable ? t('lifecycle.editReady') ?? '바꿀 내용을 검토용으로 묶었어요' : t('lifecycle.editBlocked') ?? '바꿀 내용을 발행할 수 없어요'}
        detail={publishable ? t('lifecycle.editReadyDetail') ?? '원본은 그대로예요. 묶은 변경안은 승인해야만 반영돼요.' : t('lifecycle.editBlockedDetail') ?? '제안한 변경이 의미 검증에 통과하지 못했어요.'}
      />
      {semanticDiff.length > 0 && (
        <div className="evidence-table-viewport" tabIndex={0} aria-label={t('lifecycle.semanticAria') ?? 'Reviewed semantic changes'}>
          <table className="evidence-table">
            <thead><tr><th>{t('lifecycle.colPath') ?? 'Path'}</th><th>{t('lifecycle.colBefore') ?? 'Before'}</th><th>{t('lifecycle.colAfter') ?? 'After'}</th></tr></thead>
            <tbody>
              {semanticDiff.slice(0, 12).map((change, index) => {
                const item = record(change);
                return (
                  <tr key={`${text(item?.path) ?? 'change'}:${index}`}>
                    <th scope="row" className="evidence-value-technical">{text(item?.path) ?? t('lifecycle.changeFallback', { index: index + 1 }) ?? `change ${index + 1}`}</th>
                    <td className="evidence-value-technical">{boundedValue(item?.before)}</td>
                    <td className="evidence-value-technical">{boundedValue(item?.after)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {textDiff.length > 0 && (
        <details className="evidence-audit"><summary>{t('lifecycle.textDiff') ?? 'Text diff'}</summary><pre className="evidence-text-diff">{textDiff.slice(0, 16).map(boundedValue).join('\n')}</pre></details>
      )}
      {!publishable && failedStep && <p className="evidence-safety">{t('lifecycle.validationStopped', { step: failedStep }) ?? `Validation stopped at operation ${failedStep}.`}</p>}
      {errors.length > 0 && (
        <ul className="evidence-diff-list">
          {errors.slice(0, 12).map((error, index) => {
            const item = record(error);
            return <li key={index}>{text(item?.message) ?? text(item?.code) ?? t('lifecycle.rejectedFallback') ?? 'The operation was rejected.'}</li>;
          })}
        </ul>
      )}
      <Audit rows={auditRows(result, ['transaction_id', 'source_hash', 'compiled_hash', 'spec_hash', 'context_generation'])} />
    </div>
  );
}

function PublishEvidence({ result }: { readonly result: Result }) {
  const { t } = useLocale();
  const published = result.ok !== false && Boolean(text(result.published_hash));
  return (
    <div className="evidence-lifecycle">
      <Outcome
        good={published}
        title={published ? t('lifecycle.publishDone') ?? '사례를 발행했어요' : t('lifecycle.publishUnverified') ?? '발행 확인 안 됨'}
        detail={published ? t('lifecycle.publishDoneDetail') ?? '묶은 내용을 한 번 설치했고 승인된 해시와 대조했어요.' : t('lifecycle.publishUnverifiedDetail') ?? '성공한 발행 영수증이 없어요.'}
      />
      <Audit rows={auditRows(result, ['published_hash', 'transaction_id', 'destination_rel', 'context_generation', 'idempotency_key'])} />
    </div>
  );
}

export default function LifecycleEvidence({ name, result }: { readonly name: string; readonly result: Result }) {
  switch (name) {
    case 'case_spec_validate': return <CaseSpecEvidence result={result} />;
    case 'case_spec_compile': return <CaseSpecEvidence result={result} />;
    case 'simulation_setup': return <SetupEvidence result={result} />;
    case 'run_patrol': return <PatrolEvidence result={result} />;
    case 'case_edit_plan': return <EditPlanEvidence result={result} />;
    case 'case_publish': return <PublishEvidence result={result} />;
    default: return null;
  }
}
