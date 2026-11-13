import { useEffect, useState } from 'react';
import type {
  CsvExport,
  PublicationExport,
  ResultFile,
  ResultVar,
  SeriesViewSpec,
  Profile,
} from './session';
import ResultAnalysis from './ResultAnalysis';
import ResultsInventoryRail from './ResultsInventoryRail';
import ResultReceiptMeta from './ResultReceiptMeta';
import {
  EmptyResultsPrompt,
  ResultsLoadingPrompt,
  ResultsSelectionPrompt,
} from './ResultsPrompts';
import FindingsPanel from './FindingsPanel';
import { ProfileControls } from './ProfilePanel';
import SeriesTable from './SeriesTable';
import ResultPlotTab from './ResultPlotTab';
import {
  plainVariableName,
  receiptBacked,
  resultContextLabel,
} from './resultPresentation';
import { Button } from './ui/Button';
import { OperationStatus } from './ui/OperationStatus';
import { Tabs } from './ui/Tabs';
import { useLocale } from './i18n/index.ts';
import type { useResultSeriesOverlay } from './useResultSeriesOverlay';

type ResultsLayoutProps = {
  readonly results: readonly ResultFile[];
  readonly selected: ResultFile | null;
  readonly variables: readonly ResultVar[];
  readonly overlay: ReturnType<typeof useResultSeriesOverlay>;
  readonly publication: PublicationExport | null;
  readonly csvExport: CsvExport | null;
  readonly rootLabel: string;
  readonly wsRoot: string;
  readonly activeCaseName: string | null;
  readonly workspaceCases: readonly { readonly name: string; readonly rel: string }[];
  readonly inventoryLoading: boolean;
  readonly variablesLoading: boolean;
  readonly loading: boolean;
  readonly figureExportLoading: boolean;
  readonly csvExportLoading: boolean;
  readonly error: string;
  readonly figureExportError: string;
  readonly csvExportError: string;
  readonly onOpenRun: () => void;
  readonly refreshResults: () => void;
  readonly openFile: (result: ResultFile) => void;
  readonly pickVar: (variable: ResultVar) => void;
  readonly changeView: (nextView: SeriesViewSpec) => void;
  readonly activateSeries: (key: string) => void;
  readonly exportPlot: () => void;
  readonly exportCsv: () => void;
  readonly branches: readonly string[];
  readonly timesteps: readonly number[];
  readonly branch: string | null;
  readonly timestep: number | null;
  readonly profile: Profile | null;
  readonly profileLoading: boolean;
  readonly profileError: string;
  readonly changeBranch: (branch: string) => void;
  readonly changeTimestep: (timestep: number) => void;
};

type ResultTab = 'plot' | 'table' | 'verdict';

export default function ResultsLayout(props: ResultsLayoutProps) {
  const {
    results, selected, variables: vars, overlay, publication, csvExport, rootLabel, wsRoot,
    activeCaseName, workspaceCases, inventoryLoading, variablesLoading, loading,
    figureExportLoading, csvExportLoading, error, figureExportError, csvExportError,
    onOpenRun, refreshResults, openFile, pickVar, changeView, activateSeries, exportPlot, exportCsv,
    branches, timesteps, branch, timestep, profile, profileLoading, profileError,
    changeBranch, changeTimestep,
  } = props;
  const { t } = useLocale();
  const [tab, setTab] = useState<ResultTab>('plot');
  useEffect(() => { setTab('plot'); }, [selected?.id]);
  const { viewSpec, activeSeries } = overlay;
  const varsTitle = variablesLoading
    ? t('results.loadingVars')
    : t(vars.length === 1 ? 'results.varOne' : 'results.varOther', { count: vars.length });
  const zoomed = viewSpec?.range.mode === 'bounds';
  const tableReceipt = activeSeries && overlay.activeVariable ? {
    variable: overlay.activeVariable.variable,
    position: overlay.activeVariable.position,
    rows: activeSeries.time.map((time, index) => ({ time, value: activeSeries.values[index] })),
    units: { time: activeSeries.time_unit ?? '', value: activeSeries.unit ?? '' },
    returned_rows: activeSeries.time.length,
    total_rows: activeSeries.time.length,
  } : null;

  return (
    <div className={`rv-view${results.length === 0 && !error ? ' empty' : ''}`}>
      <ResultsInventoryRail
        results={results}
        selected={selected}
        rootLabel={rootLabel}
        currentRoot={wsRoot}
        activeCaseName={activeCaseName}
        inventoryLoading={inventoryLoading}
        error={error}
        refreshResults={refreshResults}
        openFile={openFile}
      />

      <section className={'rv-main' + (!selected && !error && results.length === 0 ? ' empty' : '') + (tab === 'plot' && selected ? ' rv-main-tab-plot' : '')}>
        {!selected && error && (
          <OperationStatus
            className="rv-empty-error"
            tone="error"
            title={t('results.inventoryError')}
            detail={error}
            action={<Button variant="secondary" onClick={() => { void refreshResults(); }} busy={inventoryLoading} busyLabel={t('results.retryBusy')}>{t('results.retryResults')}</Button>}
          />
        )}
        {!selected && inventoryLoading && !error && results.length === 0 && (
          <ResultsLoadingPrompt rootLabel={rootLabel} />
        )}
        {!selected && !inventoryLoading && !error && results.length === 0 && (
          <EmptyResultsPrompt rootLabel={rootLabel} onOpenRun={onOpenRun} />
        )}
        {!selected && !error && results.length > 0 && (
          <ResultsSelectionPrompt resultCount={results.length} />
        )}
        {selected && (
          <>
            <header className="rv-head">
              <span className="ws-canvas-name">{selected.name}</span>
              <span className="ws-canvas-meta">{varsTitle}</span>
            </header>
            <div className="result-lineage" aria-label={t('results.lineageLabel')}>
              {receiptBacked(selected) ? <ResultReceiptMeta result={selected} /> : (
                <span><strong>{t('results.inventoryWord')}</strong>{resultContextLabel(selected)}</span>
              )}
            </div>
            {selected.suffix === '.ppl' && (
              <ProfileControls
                branches={branches} timesteps={timesteps} branch={branch} timestep={timestep}
                disabled={profileLoading} onBranchChange={changeBranch} onTimestepChange={changeTimestep}
              />
            )}
            <Tabs
              items={[
                { id: 'plot', label: t('results.tabPlot') },
                { id: 'table', label: t('results.tabTable') },
                { id: 'verdict', label: t('results.tabVerdict') },
              ]}
              value={tab}
              onChange={(next) => { if (next === 'plot' || next === 'table' || next === 'verdict') setTab(next); }}
              ariaLabel={t('results.tabsLabel')}
            >
              {tab === 'plot' && (
                <ResultPlotTab
                  overlay={overlay}
                  variables={vars}
                  loading={loading}
                  variablesLoading={variablesLoading}
                  error={error}
                  profile={profile}
                  profileLoading={profileLoading}
                  profileError={profileError}
                  isProfile={selected.suffix === '.ppl'}
                  onBrushRange={(start, end) => {
                    if (viewSpec) void changeView({ ...viewSpec, range: { mode: 'bounds', start, end } });
                  }}
                  onResetZoom={() => {
                    if (viewSpec) void changeView({ ...viewSpec, range: { mode: 'full' } });
                  }}
                  zoomed={zoomed}
                  pickVar={pickVar}
                  changeView={changeView}
                  activateSeries={activateSeries}
                  analysis={(overlay.activeSeries || (selected.suffix === '.ppl' && profile && !profileLoading && profileError === '')) ? (
                    <ResultAnalysis
                      selected={selected}
                      series={overlay.activeSeries}
                      figureMeta={overlay.activeSeries || !profile ? null : t('analysis.profileFigureMeta', { variable: profile.variable, branch: profile.branch })}
                      loading={loading}
                      publication={publication}
                      csvExport={csvExport}
                      figureExportLoading={figureExportLoading}
                      csvExportLoading={csvExportLoading}
                      figureExportError={figureExportError}
                      csvExportError={csvExportError}
                      exportPlot={exportPlot}
                      exportCsv={exportCsv}
                    />
                  ) : null}
                />
              )}
              {tab === 'table' && (
                tableReceipt ? <SeriesTable receipt={tableReceipt} /> : <p className="ws-empty">{t('results.pickVarHint')}</p>
              )}
              {tab === 'verdict' && (
                <FindingsPanel key={selected.id} selected={selected} variables={vars} branches={branches} genkeyHint={activeCaseName} workspaceRoot={wsRoot} workspaceCases={workspaceCases} />
              )}
            </Tabs>
          </>
        )}
      </section>
    </div>
  );
}
