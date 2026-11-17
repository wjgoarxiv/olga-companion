import { useState, useEffect, useRef } from 'react';
import { useLocale } from './i18n/index.ts';
import * as session from './session';
import ResultsLayout from './ResultsLayout';
import { createRequestEpoch } from './requestEpoch';
import { rescanResultInventory, fetchResultInventorySingleflight, readResultInventoryCache } from './resultInventoryCache';
import { pickAutoSelectResult, resultRevisionKey } from './resultPresentation';
import { useResultSeriesOverlay } from './useResultSeriesOverlay';
import { useResultExports } from './useResultExports';
import { workspaceRootLabel } from './workspaceLabels';

type ResultsViewProps = {
  readonly root: string;
  readonly activeCaseName: string | null;
  readonly onOpenRun: () => void;
  readonly preferredResultId: string | null;
  readonly onPreferredResultConsumed: () => void;
  readonly workspaceCases: readonly { readonly name: string; readonly rel: string }[];
};

/** The Results view — OLGA output as a destination, not chat scrollback. Pick a
 *  .tpl/.ppl file and plot an interactive trend. Variable search lives in the
 *  plot tab picker; the rail keeps the single inventory filter. */
export default function ResultsView({ root: wsRoot, activeCaseName, onOpenRun, preferredResultId, onPreferredResultConsumed, workspaceCases }: ResultsViewProps) {
  const cachedInventory = readResultInventoryCache(wsRoot);
  const [results, setResults] = useState<session.ResultFile[]>(cachedInventory?.results ?? []);
  const [root, setRoot] = useState(cachedInventory?.root ?? wsRoot);
  const [selected, setSelected] = useState<session.ResultFile | null>(null);
  const [vars, setVars] = useState<session.ResultVar[]>([]);
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [variablesLoading, setVariablesLoading] = useState(false);
  const [error, setError] = useState('');
  const [branches, setBranches] = useState<readonly string[]>([]);
  const [timesteps, setTimesteps] = useState<readonly number[]>([]);
  const [branch, setBranch] = useState<string | null>(null);
  const [timestep, setTimestep] = useState<number | null>(null);
  const [profile, setProfile] = useState<session.Profile | null>(null);
  const [profileVariable, setProfileVariable] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState('');
  const profileRequestRef = useRef(createRequestEpoch());
  const { t } = useLocale();
  const overlay = useResultSeriesOverlay(selected, t);
  const inventoryRequestRef = useRef(createRequestEpoch());
  const selectedIdRef = useRef<string | null>(null);
  const selectedRevisionRef = useRef<string | null>(null);
  const fileRequestRef = useRef(createRequestEpoch());
  const {
    publication,
    csvExport,
    figureExportLoading,
    csvExportLoading,
    figureExportError,
    csvExportError,
    exportPlot,
    exportCsv,
    clearExports,
  } = useResultExports({ selected, overlay, profile, branch, timestep, t });

  useEffect(() => {
    void refreshResults();
  }, []);

  // A run that finishes while Results is open hands over its output; load the list again so it shows.
  useEffect(() => {
    if (preferredResultId) void refreshResults(true);
  }, [preferredResultId]);

  async function refreshResults(rescan = false) {
    const requestId = inventoryRequestRef.current.begin();
    setInventoryLoading(true);
    setError('');
    try {
      const inventory = rescan
        ? await rescanResultInventory(wsRoot, session.fetchResults)
        : await fetchResultInventorySingleflight(wsRoot, session.fetchResults);
      if (!inventoryRequestRef.current.isCurrent(requestId)) return;
      setResults(inventory.results);
      setRoot(inventory.root);
      const currentSelectedId = selectedIdRef.current;
      const exact = preferredResultId
        ? inventory.results.find((result) => result.id === preferredResultId)
        : undefined;
      const retained = currentSelectedId
        ? inventory.results.find((result) => result.id === currentSelectedId)
        : undefined;
      if (exact && exact.id !== currentSelectedId) {
        await openFile(exact);
        onPreferredResultConsumed();
      } else if (retained && resultRevisionKey(retained) !== selectedRevisionRef.current) {
        await openFile(retained);
      } else if (retained) {
        selectedIdRef.current = retained.id;
        selectedRevisionRef.current = resultRevisionKey(retained);
        setSelected(retained);
      } else if (!currentSelectedId) {
        const auto = pickAutoSelectResult(inventory.results, activeCaseName, {
          selectedId: currentSelectedId,
          preferredId: preferredResultId,
        });
        if (auto) {
          await openFile(auto);
        }
      } else if (currentSelectedId) {
        selectedIdRef.current = null;
        selectedRevisionRef.current = null;
        fileRequestRef.current.invalidate();
        overlay.reset();
        clearExports();
        setSelected(null);
        setVars([]);
        setVariablesLoading(false);
      }
    } catch (e) {
      if (inventoryRequestRef.current.isCurrent(requestId)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (inventoryRequestRef.current.isCurrent(requestId)) setInventoryLoading(false);
    }
  }

  async function openFile(f: session.ResultFile) {
    inventoryRequestRef.current.invalidate();
    selectedIdRef.current = f.id;
    selectedRevisionRef.current = resultRevisionKey(f);
    const requestId = fileRequestRef.current.begin();
    overlay.reset();
    clearExports();
    profileRequestRef.current.invalidate();
    setInventoryLoading(false); setSelected(f); setVars([]); setError(''); setVariablesLoading(true);
    setBranches([]); setTimesteps([]); setBranch(null); setTimestep(null); setProfile(null); setProfileVariable(null); setProfileError(''); setProfileLoading(false);
    try {
      const v = await session.loadResultVars(f.id);
      if (fileRequestRef.current.isCurrent(requestId)) {
        setVars(v.variables || []);
        setBranches(v.branches ?? []);
        setTimesteps(v.timesteps ?? []);
        setBranch((v.branches ?? [])[0] ?? null);
        setTimestep((v.timesteps ?? []).length ? (v.timesteps ?? [])[(v.timesteps ?? []).length - 1] : null);
      }
    } catch (e) {
      if (fileRequestRef.current.isCurrent(requestId)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (fileRequestRef.current.isCurrent(requestId)) setVariablesLoading(false);
    }
  }

  async function pickVar(variable: session.ResultVar): Promise<void> {
    clearExports();
    if (selected?.suffix === '.ppl') {
      await loadProfile(variable.variable, branch, timestep);
      return;
    }
    await overlay.toggleVariable(variable);
  }

  /** Spatial profile for one .ppl variable on one branch at one time. */
  async function loadProfile(
    variable: string | null,
    nextBranch: string | null,
    nextTimestep: number | null,
  ): Promise<void> {
    if (!selected || !variable || !nextBranch) return;
    const requestId = profileRequestRef.current.begin();
    setProfileVariable(variable);
    setProfileError('');
    setProfileLoading(true);
    try {
      const next = await session.fetchProfile(
        selected.id, variable, nextBranch, nextTimestep ?? undefined,
      );
      if (profileRequestRef.current.isCurrent(requestId)) setProfile(next);
    } catch (cause) {
      if (!profileRequestRef.current.isCurrent(requestId)) return;
      setProfile(null);
      setProfileError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (profileRequestRef.current.isCurrent(requestId)) setProfileLoading(false);
    }
  }

  async function changeBranch(next: string): Promise<void> {
    clearExports();
    setBranch(next);
    await loadProfile(profileVariable, next, timestep);
  }

  async function changeTimestep(next: number): Promise<void> {
    clearExports();
    setTimestep(next);
    await loadProfile(profileVariable, branch, next);
  }

  /** Choosing another legend series changes what an export would describe. */
  function activateSeries(key: string): void {
    clearExports();
    overlay.activateSeries(key);
  }

  async function changeView(nextView: session.SeriesViewSpec): Promise<void> {
    clearExports();
    await overlay.changeView(nextView);
  }

  const rootLabel = workspaceRootLabel(root);

  return (
    <ResultsLayout
      results={results} selected={selected} variables={vars}
      overlay={overlay}
      publication={publication} csvExport={csvExport} rootLabel={rootLabel} wsRoot={root} activeCaseName={activeCaseName} workspaceCases={workspaceCases}
      inventoryLoading={inventoryLoading} variablesLoading={variablesLoading} loading={overlay.loading}
      figureExportLoading={figureExportLoading} csvExportLoading={csvExportLoading} error={error || overlay.error}
      figureExportError={figureExportError} csvExportError={csvExportError} onOpenRun={onOpenRun}
      refreshResults={refreshResults} openFile={openFile} pickVar={pickVar}
      changeView={changeView} activateSeries={activateSeries}
      exportPlot={exportPlot} exportCsv={exportCsv}
      branches={branches} timesteps={timesteps} branch={branch} timestep={timestep}
      profile={profile} profileLoading={profileLoading}
      profileError={profileError} changeBranch={changeBranch} changeTimestep={changeTimestep}
    />
  );
}
