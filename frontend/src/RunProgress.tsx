import type { SolverProgress } from './session';
import { effectiveSolverProgress, progressAttributes } from './progressPresentation';
import { useLocale } from './i18n/index.ts';
import type { I18nKey } from './i18n/ko.ts';
import { runStateLabel } from './runReason.ts';

type RunProgressProps = {
  readonly progress: SolverProgress;
  readonly cancelRequested?: boolean;
  readonly supervisionUnknown?: boolean;
  readonly compact?: boolean;
};

type ProgressText = (key: I18nKey, vars?: Record<string, string | number>) => string;

function formatSimulationTime(seconds: number, t: ProgressText): string {
  const whole = seconds.toLocaleString();
  if (seconds >= 3600) {
    const hours = (seconds / 3600).toFixed(2);
    return t('run.simHours', { value: hours, seconds: whole }) ?? `${hours} h (${whole} s)`;
  }
  if (seconds >= 60) {
    const minutes = (seconds / 60).toFixed(2);
    return t('run.simMinutes', { value: minutes, seconds: whole }) ?? `${minutes} min (${whole} s)`;
  }
  return t('run.simSeconds', { seconds: whole }) ?? `${whole} s`;
}

function phaseWord(phase: string, t: ProgressText, finished = false): string {
  if (finished && phase === 'indeterminate') return t('run.state.terminal');
  const known = new Set(['ready', 'starting', 'running', 'finalizing', 'completed', 'failed', 'cancelled', 'timed_out', 'terminal', 'indeterminate', 'supervision_unknown']);
  if (known.has(phase)) return runStateLabel(phase, t);
  return phase
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function activityLabel(progress: SolverProgress, t: ProgressText): string {
  if (progress.activity_status === 'terminal') return t('run.activity.terminal');
  if (progress.activity_status === 'active') return t('run.activity.active');
  if (progress.activity_status === 'clock_skew') return t('run.activity.skew');
  if (progress.activity_status === 'stale') {
    const age = progress.age_seconds == null ? '' : t('run.activity.staleAge', { age: Math.round(progress.age_seconds) });
    return `${t('run.activity.stale')}${age}`;
  }
  return progress.parse_status === 'unreadable' ? t('run.activity.unreadable') : t('run.activity.unavailable');
}

function livenessLabel(liveness: SolverProgress['liveness'], t: ProgressText, finished = false): string {
  if (liveness === 'supervised') return t('run.live.supervised');
  if (liveness === 'terminal') return t('run.live.terminal');
  if (liveness === 'supervision_unknown') return t('run.live.unknown');
  if (finished) return t('run.live.exited');
  return t('run.live.indeterminate');
}

export function RunProgress({ progress, cancelRequested = false, supervisionUnknown = false, compact = false }: RunProgressProps) {
  const { t } = useLocale();
  const effective = effectiveSolverProgress(progress, supervisionUnknown);
  const fractionAttributes = progressAttributes(effective.fraction, effective.vendor_percent);
  const hasVendorFraction = 'value' in fractionAttributes;
  const finished = effective.activity_status === 'terminal';
  const phaseLabel = effective.last_known
    ? t('run.progressLastKnown', { phase: phaseWord(effective.last_known_phase || 'indeterminate', t, finished) })
    : phaseWord(effective.phase, t, finished);
  const lastKnownSuffix = effective.last_known ? ` · ${t('run.vendorLastKnownSuffix')}` : '';
  const announcement = [
    `${t('run.phase')} ${phaseLabel}`,
    cancelRequested ? t('run.cancelledSuffix') : '',
    hasVendorFraction ? t('run.vendorLastKnown', { percent: String(effective.vendor_percent) }) : '',
  ].filter(Boolean).join(' · ');

  return (
    <section className={`run-progress${compact ? ' run-progress-compact' : ''}`} aria-label={t('run.progressAria')}>
      <p className="ui-visually-hidden" aria-live="polite" aria-atomic="true">{announcement}</p>
      <dl className="run-progress-status">
        <div>
          <dt>{t('run.phase')}</dt>
          <dd>{phaseLabel}{cancelRequested ? ` · ${t('run.cancelledSuffix')}` : ''}</dd>
        </div>
        <div>
          <dt>{t('run.liveness')}</dt>
          <dd>{livenessLabel(effective.liveness, t, finished)}</dd>
        </div>
        <div>
          <dt>{t('run.activity')}</dt>
          <dd>{activityLabel(effective, t)}</dd>
        </div>
      </dl>

      <div className="run-progress-meter">
        <progress aria-label={t('run.vendorAria')} {...fractionAttributes} />
        <span>
          {hasVendorFraction
            ? `${t('run.vendorProgress', { percent: (effective.vendor_percent ?? 0).toFixed(1) })}${lastKnownSuffix}`
            : t('run.noVendor')}
        </span>
      </div>

      {(effective.simulation_time_s != null || effective.step != null || effective.step_size_s != null) && (
        <dl className="run-progress-evidence">
          {effective.simulation_time_s != null && (
            <div><dt>{t('run.simTime')}</dt><dd>{formatSimulationTime(effective.simulation_time_s, t)}{lastKnownSuffix}</dd></div>
          )}
          {effective.step != null && (
            <div>
              <dt>{t('run.solverStep')}</dt>
              <dd>
                {effective.step.toLocaleString()}
                {effective.adaptive_total_steps != null ? t('run.adaptiveEst', { count: effective.adaptive_total_steps }) : ''}
                {lastKnownSuffix}
              </dd>
            </div>
          )}
          {effective.step_size_s != null && (
            <div><dt>{t('run.stepSize')}</dt><dd>{effective.step_size_s.toLocaleString()} s{lastKnownSuffix}</dd></div>
          )}
        </dl>
      )}
    </section>
  );
}
