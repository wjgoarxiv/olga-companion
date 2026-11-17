import { useEffect, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { compactValue } from './util';
import TopologyMap, { type NetNode, type NetEdge } from './TopologyMap';
import ArtifactCard from './ArtifactCard';
import SeriesTable from './SeriesTable';
import { isArtifactReceipt, presentSeriesTable } from './resultPresentation';
import * as session from './session';
import LifecycleEvidence, { isLifecycleEvidence } from './LifecycleEvidence';
import InspectionEvidence from './InspectionEvidence';
import { presentInspectionEvidence } from './inspectionPresentation';
import TabCompareView from './TabCompareView';
import PipeTableDraftCard from './PipeTableDraftCard';
import { presentPipeDraft } from './pipeTableDraft.ts';

function AuthenticatedResultImage({ path, alt }: { readonly path: string; readonly alt: string }) {
  const { t } = useLocale();
  const [source, setSource] = useState('');
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = '';
    setSource('');
    setLoadError('');
    void session.fetchResultImage(path, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setSource(objectUrl);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(cause instanceof session.ResultImageError
          ? t('evidence.imageFailed') ?? 'Result image could not be loaded.'
          : cause instanceof Error ? cause.message : t('evidence.imageFailed') ?? 'Result image could not be loaded.');
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (loadError) return <p className="error">{loadError}</p>;
  return source ? <img src={source} alt={alt} /> : null;
}

/** Evidence is the photography of this app: a tool result rendered as inspectable
 *  proof. Plots become images (via the sidecar download route); text-bearing
 *  results (validation, summary, topology, reports) show their captured output;
 *  everything else shows a compact key/value read-out. Status stays text-only per
 *  the design law (no filled badges); paths collapse to basenames so the timeline
 *  never leaks an absolute path or scrolls sideways. Rendered inside a ToolUnit,
 *  which supplies the name header. */
export default function EvidenceBlock({
  name,
  result,
  currentWorkspaceGeneration,
}: {
  name: string;
  result: Record<string, unknown>;
  currentWorkspaceGeneration?: number;
}) {
  const { t } = useLocale();
  const plots = (result.plots as string[]) || [];
  const imagePath = (result.image_path as string) || (typeof result.figure === 'string' ? result.figure : '');
  const textFields = ['preview', 'summary', 'summary_text', 'report', 'markdown', 'stdout'];
  const text = textFields.map((k) => result[k]).find((v) => typeof v === 'string' && v) as string | undefined;

  const status = 'ok' in result ? (result.ok ? 'good' : 'bad') : undefined;
  const error = typeof result.error === 'string' ? result.error : undefined;

  // A parsed network graph (genkey_topology) renders as the interactive map.
  const isNetwork = Array.isArray(result.nodes) && Array.isArray(result.edges) && 'counts' in result;
  const isSeries = name === 'results_series' && presentSeriesTable(result) !== null;
  const isArtifact = isArtifactReceipt(result);
  const isLifecycle = isLifecycleEvidence(name);
  const inspection = presentInspectionEvidence(name, result, t);
  const isTabCompare = name === 'fluids_compare_tab';
  const pipeDraft = presentPipeDraft(name, result);

  const rows = Object.entries(result)
    .filter(([k]) => !['command', 'ok', 'error', 'plots', 'image_path', 'figure', 'nodes', 'edges', 'counts', 'truncated', ...textFields].includes(k))
    .slice(0, 8);

  return (
    <section className="evidence-block" aria-label={t('evidence.blockAria', { name }) ?? `Evidence: ${name}`}>
      {status && <p className={`status ${status}`}>{result.ok ? 'OK' : t('evidence.attentionState') ?? 'Attention'}</p>}
      {error && <p className="error">{error}</p>}
      {isLifecycle && <LifecycleEvidence name={name} result={result} />}
      {inspection && <InspectionEvidence presentation={inspection} />}
      {isTabCompare && <TabCompareView result={result} />}
      {pipeDraft && <PipeTableDraftCard view={pipeDraft} />}
      {isSeries && <SeriesTable receipt={result} />}
      {isArtifact && <ArtifactCard receipt={result} currentWorkspaceGeneration={currentWorkspaceGeneration} />}
      {isNetwork && (
        <TopologyMap
          nodes={result.nodes as NetNode[]}
          edges={result.edges as NetEdge[]}
          counts={result.counts as { nodes: number; flowpaths: number; edges: number }}
          truncated={Boolean(result.truncated)}
        />
      )}
      {plots.map((p) => (
        <div className="evidence-plot-viewport" key={p} tabIndex={0}>
          <AuthenticatedResultImage path={p} alt={t('evidence.plotAlt', { name }) ?? `${name} plot`} />
        </div>
      ))}
      {imagePath && <div className="evidence-plot-viewport" tabIndex={0}><AuthenticatedResultImage key={imagePath} path={imagePath} alt={t('evidence.figureAlt', { name }) ?? `${name} figure`} /></div>}
      {text && !inspection && !isTabCompare && <pre className="evidence-value-technical">{text.slice(0, 6000)}</pre>}
      {!pipeDraft && !inspection && !isTabCompare && !isLifecycle && !isNetwork && !isSeries && !isArtifact && !text && !plots.length && !imagePath && rows.length > 0 && (
        <dl>
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd className={/(?:hash|sha|id|path|rel|token|command)/i.test(k) ? 'evidence-value-technical' : undefined} title={typeof v === 'string' ? v : undefined}>{compactValue(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
