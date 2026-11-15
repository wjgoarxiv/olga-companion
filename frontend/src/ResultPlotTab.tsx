import { useEffect, useRef } from 'react';
import CalibrationRail from './CalibrationRail';
import GlossaryTerm from './GlossaryTerm';
import ProfilePanel from './ProfilePanel';
import { FrameDecor } from './ui/FrameDecor';
import TrendChart from './TrendChart';
import ResultAnalysis from './ResultAnalysis';
import VariablePicker from './VariablePicker';
import type { ResultVar, SeriesViewSpec } from './session';
import { useLocale } from './i18n/index.ts';
import { Skeleton } from './ui/Skeleton';
import { OperationStatus } from './ui/OperationStatus';
import { Button } from './ui/Button';
import { pickAutoPlotVariable } from './trendGeometry';
import { resultVariableKey, type useResultSeriesOverlay } from './useResultSeriesOverlay';
import type { Profile } from './session';

type Overlay = ReturnType<typeof useResultSeriesOverlay>;

export default function ResultPlotTab({
  overlay,
  variables,
  loading,
  variablesLoading,
  error,
  profile,
  profileLoading,
  profileError,
  isProfile,
  onBrushRange,
  onResetZoom,
  zoomed,
  analysis,
  pickVar,
  changeView,
  activateSeries,
}: {
  readonly overlay: Overlay;
  readonly variables: readonly ResultVar[];
  readonly loading: boolean;
  readonly variablesLoading: boolean;
  readonly error: string;
  readonly profile: Profile | null;
  readonly profileLoading: boolean;
  readonly profileError: string;
  readonly isProfile: boolean;
  readonly onBrushRange: (start: number, end: number) => void;
  readonly onResetZoom: () => void;
  readonly zoomed: boolean;
  readonly analysis: React.ReactNode;
  readonly pickVar: (variable: ResultVar) => void;
  readonly changeView: (nextView: SeriesViewSpec) => void;
  readonly activateSeries: (key: string) => void;
}) {
  const { t } = useLocale();
  const { plottedSeries, activeSeriesKey, activeSeries, viewSpec } = overlay;
  // Profiles plot through pickVar (branch/timestep aware); trends through the overlay.
  // The attempt resets whenever a new variable list arrives (openFile refetches),
  // so reselecting a file re-plots even though the keys match the last attempt.
  const autoProfileRef = useRef<{ vars: readonly ResultVar[] | null; scope: string | null }>({ vars: null, scope: null });
  useEffect(() => {
    if (!isProfile) {
      overlay.ensureAutoPlot(variables);
      return;
    }
    if (profile || profileLoading || profileError !== '') return;
    const attempt = autoProfileRef.current;
    if (attempt.vars !== variables) {
      attempt.vars = variables;
      attempt.scope = null;
    }
    const scope = variables.map((v) => resultVariableKey(v)).join('|');
    if (scope === '' || attempt.scope === scope) return;
    const choice = pickAutoPlotVariable(variables);
    if (!choice) return;
    attempt.scope = scope;
    void pickVar(choice);
  }, [isProfile, overlay, variables, profile, profileLoading, profileError, pickVar]);

  return (
    <div className="rv-plot">
      <div className="rv-plot-side">
        <VariablePicker
          variables={variables}
          plottedKeys={plottedSeries.map((item) => item.key)}
          disabled={loading || variablesLoading}
          onToggle={(v) => { void pickVar(v); }}
        />
        {plottedSeries.length > 0 && (
          <ul className="rv-chips" aria-label={t('results.overlays')}>
            {plottedSeries.map((item) => (
              <li key={item.key} className="rv-chip">
                <button
                  type="button"
                  aria-pressed={item.key === activeSeriesKey}
                  onClick={() => activateSeries(item.key)}
                  title={`${item.variable.variable} · ${item.variable.position}`}
                >
                  <span className="rv-chip-dot" style={{ background: item.color }} />
                  <GlossaryTerm term={item.variable.variable}>{item.variable.variable} · {item.variable.position}</GlossaryTerm>
                </button>
                <button type="button" aria-label={t('results.removeOverlay', { name: item.variable.variable })} onClick={() => { void overlay.toggleVariable(item.variable); }}>×</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rv-chart" data-tour="result-graph">
        {(loading || variablesLoading) && (
          <div className="rv-chart-loading" aria-hidden="true">
            <Skeleton className="rv-loading" loadingLabel={variablesLoading ? t('results.loadingVars') : t('results.scanning')} lines={variablesLoading ? 6 : 4} visuallyHidden={false} />
          </div>
        )}
        {error !== '' && <OperationStatus tone="error" title={variablesLoading ? t('results.varsError') : t('results.viewError')} detail={error} />}
        {isProfile && <ProfilePanel profile={profile} loading={profileLoading} error={profileError} />}
        {!isProfile && !loading && !variablesLoading && !activeSeries && error === '' && (
          <p className="ws-empty">{t('results.pickVarHint')}</p>
        )}
        {!isProfile && activeSeries && viewSpec && (
          <>
            <div className="rv-chart-wrap">
              <FrameDecor />
              {zoomed && (
                <Button variant="secondary" className="rv-zoom-reset" onClick={onResetZoom}>
                  {t('results.resetZoom')}
                </Button>
              )}
              <TrendChart
                key={`${overlay.activeSeriesKey}:${viewSpec.range.mode === 'bounds' ? `${viewSpec.range.start}-${viewSpec.range.end}` : viewSpec.range.mode}`}
                series={activeSeries}
                overlays={plottedSeries.filter((item) => item.key !== overlay.activeSeriesKey).map((item) => ({ key: item.key, series: item.series, color: item.color }))}
                unit={overlay.activeVariable?.unit}
                onBrushRange={onBrushRange}
              />
            </div>
            <CalibrationRail series={activeSeries} view={viewSpec} disabled={loading} onChange={(nextView) => { void changeView(nextView); }} />
          </>
        )}
        {analysis}
      </div>
    </div>
  );
}
