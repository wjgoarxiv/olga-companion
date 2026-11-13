import { useRef, useState } from 'react';
import * as session from './session';
import type { TranslateFn } from './i18n/index.ts';
import type { useResultSeriesOverlay } from './useResultSeriesOverlay';
import { createRequestEpoch } from './requestEpoch';
import { rememberSessionFigures } from './sessionFigures';

type OverlaySlice = Pick<ReturnType<typeof useResultSeriesOverlay>, 'activeVariable' | 'viewSpec'>;

/* Trend + profile CSV/figure export state machine. Extracted from ResultsView
 * so the route entrypoint stays a bounded orchestrator; the request epochs,
 * error paths and the profile payload mapping below are unchanged. */
export function useResultExports(args: {
  readonly selected: session.ResultFile | null;
  readonly overlay: OverlaySlice;
  readonly profile: session.Profile | null;
  readonly branch: string | null;
  readonly timestep: number | null;
  readonly t: TranslateFn;
}) {
  const { selected, overlay, profile, branch, timestep, t } = args;
  const [publication, setPublication] = useState<session.PublicationExport | null>(null);
  const [csvExport, setCsvExport] = useState<session.CsvExport | null>(null);
  const [figureExportLoading, setFigureExportLoading] = useState(false);
  const [csvExportLoading, setCsvExportLoading] = useState(false);
  const [figureExportError, setFigureExportError] = useState('');
  const [csvExportError, setCsvExportError] = useState('');
  const figureExportRequestRef = useRef(createRequestEpoch());
  const csvExportRequestRef = useRef(createRequestEpoch());

  function clearExports(): void {
    figureExportRequestRef.current.invalidate();
    csvExportRequestRef.current.invalidate();
    // The superseded request's own finally no longer clears these, so reset them here.
    setFigureExportLoading(false); setCsvExportLoading(false);
    setPublication(null); setCsvExport(null); setFigureExportError(''); setCsvExportError('');
  }

  async function exportPlot(): Promise<void> {
    if (!selected) return;
    const requestId = figureExportRequestRef.current.begin();
    setFigureExportError(''); setFigureExportLoading(true);
    try {
      if (selected.suffix === '.ppl') {
        if (!profile || !branch) throw new Error(t('analysis.figureFailed') ?? 'Figure export failed');
        const exported = await session.exportProfilePlot(selected.id, profile.variable, branch);
        if (!exported.ok || exported.plots.length === 0) throw new Error(t('analysis.figureFailed') ?? 'Figure export failed');
        if (figureExportRequestRef.current.isCurrent(requestId)) {
          setPublication(exported);
          rememberSessionFigures(exported.plots);
        }
      } else {
        if (!overlay.activeVariable || !overlay.viewSpec) return;
        const exported = await session.exportPublicationPlot(selected.id, overlay.activeVariable.variable, overlay.activeVariable.position, overlay.viewSpec);
        if (figureExportRequestRef.current.isCurrent(requestId)) {
          setPublication(exported);
          rememberSessionFigures(exported.plots);
        }
      }
    } catch (e) {
      if (figureExportRequestRef.current.isCurrent(requestId)) setFigureExportError(e instanceof Error ? e.message : String(e));
    } finally {
      if (figureExportRequestRef.current.isCurrent(requestId)) setFigureExportLoading(false);
    }
  }

  async function exportCsv(): Promise<void> {
    if (!selected) return;
    const requestId = csvExportRequestRef.current.begin();
    setCsvExportError(''); setCsvExportLoading(true);
    try {
      if (selected.suffix === '.ppl') {
        if (!profile || !branch) throw new Error(t('analysis.csvFailed') ?? 'CSV export failed');
        const exported = await session.exportProfileCsv(selected.id, profile.variable, branch, timestep ?? undefined);
        if (!exported.ok || !exported.csv) throw new Error(t('analysis.csvFailed') ?? 'CSV export failed');
        if (csvExportRequestRef.current.isCurrent(requestId)) {
          setCsvExport({
            variable: profile.variable,
            position: profile.branch,
            unit: profile.unit,
            download_path: exported.csv,
            row_count: profile.values.length,
          });
        }
      } else {
        if (!overlay.activeVariable || !overlay.viewSpec) return;
        const exported = await session.exportSelectedCsv(selected.id, overlay.activeVariable.variable, overlay.activeVariable.position, overlay.viewSpec);
        if (csvExportRequestRef.current.isCurrent(requestId)) setCsvExport(exported);
      }
    } catch (e) {
      if (csvExportRequestRef.current.isCurrent(requestId)) setCsvExportError(e instanceof Error ? e.message : String(e));
    } finally {
      if (csvExportRequestRef.current.isCurrent(requestId)) setCsvExportLoading(false);
    }
  }

  return {
    publication,
    csvExport,
    figureExportLoading,
    csvExportLoading,
    figureExportError,
    csvExportError,
    exportPlot,
    exportCsv,
    clearExports,
  };
}
