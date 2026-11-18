import { useEffect, useState } from 'react';
import { RunProgress } from './RunProgress';
import type { ResultVar, Series, SeriesViewSpec, SweepCaseStatus, SweepStatus } from './session';
import { fetchSeries } from './session';
import TrendChart from './TrendChart';
import SweepSummaryTable from './SweepSummaryTable';
import { sweepSummary, type SweepSummaryRow } from './sweepApi';
import { useLocale } from './i18n/index.ts';
import type { PlottedSeries } from './useResultSeriesOverlay';

type RunSweepStatusProps = {
  readonly preview: SweepStatus | null;
  readonly status: SweepStatus | null;
  readonly supervisionUnknown?: boolean;
};

const SWEEP_STATE_KEYS: Readonly<Record<string, string>> = {
  queued: 'run.sweep.queued',
  preview: 'run.sweep.preview',
  running: 'run.sweep.running',
  completed: 'run.sweep.completed',
  failed: 'run.sweep.failed',
  cancelled: 'run.sweep.cancelled',
  timed_out: 'run.sweep.timed_out',
};

export function formatSweepState(state: string, t: (key: string) => string): string {
  const key = SWEEP_STATE_KEYS[state];
  return key ? t(key) : state;
}

function formatCaseLabel(item: SweepCaseStatus, t: (key: string, vars?: Record<string, string | number>) => string): string {
  return t('run.sweepCase', { index: String(item.index + 1).padStart(2, '0') });
}

function caseDetail(item: SweepCaseStatus, t: (key: string, vars?: Record<string, string | number>) => string): string {
  if (item.error) return item.error;
  if (item.pvt_files.length > 0) return t('run.sweepPvtReady', { count: item.pvt_files.length });
  if (item.run_id) return t('run.sweepAccepted');
  return t('run.sweepWaiting');
}

const TERMINAL_SWEEP_STATES = new Set(['completed', 'failed', 'cancelled', 'timed_out']);
const SWEEP_OVERLAY_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)'];

function toPlottedSeries(row: SweepSummaryRow, series: Series, color: string): PlottedSeries {
  const variable: ResultVar = {
    index: 0,
    variable: series.variable,
    position: series.position ?? '',
    unit: series.unit ?? '',
    description: series.description ?? '',
  };
  const view: SeriesViewSpec = { quantity_kind: 'point', range: { mode: 'full' } };
  return {
    key: `${row.index}:${series.variable}`,
    variable,
    series,
    view,
    color,
  };
}

export function RunSweepStatus({ preview, status, supervisionUnknown = false }: RunSweepStatusProps) {
  const { t } = useLocale();
  const [summary, setSummary] = useState<SweepSummaryRow[] | null>(null);
  const [overlay, setOverlay] = useState<readonly PlottedSeries[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const current = status ?? preview;
  const cases = status?.cases ?? preview?.cases ?? [];
  const state = current?.state ?? 'ready';
  const caseCount = current?.case_count ?? 0;
  const completedCount = cases.filter((item) => item.state === 'completed').length;
  const activeCount = cases.filter((item) => item.state === 'running' || item.state === 'finalizing' || item.state === 'supervision_unknown' || item.cancel_requested).length;
  const sweepId = current?.sweep_id ?? null;
  const sweepState = current?.state ?? 'ready';

  useEffect(() => {
    if (!sweepId || !TERMINAL_SWEEP_STATES.has(sweepState)) {
      setSummary(null);
      setOverlay([]);
      setActiveKey(null);
      return;
    }
    let cancelled = false;
    sweepSummary(sweepId).then(
      (result) => {
        if (cancelled) return;
        setSummary(result.rows);
        const plottable = result.rows.filter((row) => row.ok && row.tpl);
        void Promise.allSettled(
          plottable.map((row) => row.tpl ? fetchSeries(row.tpl, 'PT') : Promise.reject(new Error('no tpl'))),
        ).then((settled) => {
          if (cancelled) return;
          const plotted = settled.flatMap((entry, position) => {
            if (entry.status !== 'fulfilled') return [];
            const row = plottable[position];
            return [toPlottedSeries(row, entry.value, SWEEP_OVERLAY_COLORS[position % SWEEP_OVERLAY_COLORS.length])];
          });
          setOverlay(plotted);
          setActiveKey(plotted.length > 0 ? plotted[plotted.length - 1].key : null);
        });
      },
      () => {
        if (!cancelled) setSummary([]);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [sweepId, sweepState]);

  return (
    <div className="sweep-status" aria-label={t('run.sweepStatusAria')}>
      <div className="sweep-status-grid">
        <span className="sweep-status-card">
          <strong>{t('run.sweepPlan')}</strong>
          <em>{caseCount > 0 ? t('run.sweepPlanned', { count: caseCount }) : t('run.sweepPreviewReady')}</em>
        </span>
        <span className="sweep-status-card">
          <strong>{t('run.sweepCaseCount')}</strong>
          <em>{t('run.sweepCounts', { done: completedCount, active: activeCount })}</em>
        </span>
      </div>

      {current && (
        <p className="sweep-summary">
          {current.dry_run ? t('run.sweepNeedsApproval') : t('run.sweepPhase', { state: formatSweepState(state, t) })}
        </p>
      )}

      {cases.length > 0 ? (
        <ol className="sweep-case-list" aria-label={t('run.sweepCasesAria')}>
          {cases.map((item) => (
            <li key={item.index} className={'sweep-case-card sweep-' + item.state}>
              <span className="sweep-case-index">{formatCaseLabel(item, t)}</span>
              <span className="sweep-case-copy">
                <strong>{formatSweepState(item.state, t)}</strong>
                <em>{caseDetail(item, t)}</em>
                {item.run_id && (
                  <RunProgress
                    progress={item.solver_progress}
                    cancelRequested={item.cancel_requested}
                    supervisionUnknown={supervisionUnknown}
                    compact
                  />
                )}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="sweep-standby">{t('run.sweepStandby')}</p>
      )}

      {summary && summary.length > 0 && (
        <div className="sweep-summary-results" aria-label={t('run.sweepResultsAria')}>
          <SweepSummaryTable rows={summary} />
          {overlay.length > 0 && (() => {
            const current = overlay.find((item) => item.key === activeKey) ?? overlay[0];
            const rest = overlay.filter((item) => item.key !== current.key);
            return <TrendChart series={current.series} overlays={rest} />;
          })()}
        </div>
      )}
    </div>
  );
}
