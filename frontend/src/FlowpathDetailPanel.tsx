import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react';
import FlowpathGeometryViewer from './FlowpathGeometryViewer';
import { PanelResizeHandle } from './PanelResizeHandle';
import { readLocalStorage, writeLocalStorage } from './safeLocalStorage';
import { useLocale } from './i18n/index.ts';
import type { TranslateFn } from './i18n/index.ts';
import { ActivityLoader } from './ui/ActivityLoader';
import { RollingNumber } from './ui/RollingNumber';
import type { FlowpathDetails, FlowpathPoint } from './workspaceApi';

type FlowpathDetailPanelProps = {
  readonly label: string;
  readonly source: string;
  readonly target: string;
  readonly details: FlowpathDetails | null;
  readonly loading: boolean;
  readonly error: string;
  readonly onBack: () => void;
};

const DETAILS_OPEN_KEY = 'olga_flowpath_details_open';

function initialDetailsOpen() {
  return readLocalStorage(DETAILS_OPEN_KEY) !== 'closed';
}

function metric(value: number, digits = 2) {
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function point(value: FlowpathPoint, t: TranslateFn) {
  const triple = `${metric(value.x_m, 3)}, ${metric(value.y_m, 3)}, ${metric(value.z_m, 3)}`;
  return t('flowpath.pointMeters', { value: triple }) ?? `(${triple}) m`;
}

function diameterRange(details: FlowpathDetails, t: TranslateFn) {
  const minimum = details.summary.diameter_min_m;
  const maximum = details.summary.diameter_max_m;
  if (minimum == null || maximum == null) return '—';
  const low = metric(minimum * 1000, 1);
  const high = metric(maximum * 1000, 1);
  return low === high
    ? t('flowpath.mmSingle', { value: low }) ?? `${low} mm`
    : t('flowpath.mmRange', { low, high }) ?? `${low}–${high} mm`;
}

export default function FlowpathDetailPanel({
  label, source, target, details, loading, error, onBack,
}: FlowpathDetailPanelProps) {
  const { t } = useLocale();
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(initialDetailsOpen);
  const selectSection = useCallback((index: number | null) => setSelectedIndex(index), []);
  useEffect(() => {
    setSelectedIndex(null);
    headingRef.current?.focus();
  }, [label]);
  const selected = selectedIndex == null ? null : details?.sections[selectedIndex] ?? null;
  const ready = details?.geometry.status === 'ready';

  function handleDetailsToggle(event: SyntheticEvent<HTMLDetailsElement>) {
    const open = event.currentTarget.open;
    setDetailsOpen(open);
    writeLocalStorage(DETAILS_OPEN_KEY, open ? 'open' : 'closed');
  }

  return (
    <section className="flowpath-studio" aria-labelledby="flowpath-studio-title">
      <header className="flowpath-studio-head">
        <button type="button" className="flowpath-back" onClick={onBack}>{t('flowpath.back')}</button>
        <div>
          <p className="flowpath-studio-eyebrow">{t('flowpath.eyebrow')}</p>
          <h2 id="flowpath-studio-title" ref={headingRef} tabIndex={-1}>{label}</h2>
          <p>{source} → {target}</p>
        </div>
        {details && <span className="flowpath-studio-count">{t('flowpath.pipeCount', { count: details.summary.pipe_count })} · {t('flowpath.sectionCount', { count: details.summary.segment_count })}</span>}
      </header>
      {loading && <ActivityLoader className="flowpath-progress" loadingLabel="Reading endpoint and section geometry…" />}
      {error && <p className="flowpath-studio-error" role="alert">{error}</p>}
      {details && (
        <div className="flowpath-studio-body">
          <div className="flowpath-geometry-stage">
            {ready ? (
              <FlowpathGeometryViewer
                sections={details.sections}
                selectedIndex={selectedIndex}
                onSelect={selectSection}
                profileOnly={details.geometry.status === 'ready' && details.geometry.source === 'length_elevation'}
              />
            ) : (
              <div className="flowpath-unavailable" role="status">
                <strong>{t('flowpath.geometryUnavailable') ?? 'Geometry view unavailable'}</strong>
                <span>{details.geometry.status === 'unavailable' ? details.geometry.reason.replaceAll('_', ' ') : t('flowpath.unsupportedGeometry') ?? 'Unsupported geometry'}</span>
                <small>{t('flowpath.geometryNote') ?? 'The parsed numeric summary remains available; no centerline was fabricated.'}</small>
              </div>
            )}
          </div>
          <PanelResizeHandle
            targetRef={drawerRef}
            targetId="flowpath-summary-drawer"
            label={t('flowpath.resizeDrawer') ?? 'Resize flowpath summary drawer'}
            storageKey="olga_panel_flowpath_summary"
            defaultWidth={330}
            minWidth={272}
            maxWidth={520}
            direction="grow-left"
            className="flowpath-drawer-resizer"
          />
          <aside ref={drawerRef} id="flowpath-summary-drawer" className="flowpath-summary-drawer" aria-label={t('flowpath.detailsAria', { label }) ?? `Flowpath details for ${label}`}>
            <details open={detailsOpen} onToggle={handleDetailsToggle}>
              <summary>{t('flowpath.geometryDetails') ?? 'Geometry details'}</summary>
              <dl className="topo-detail-metrics">
                <div><dt>{t('flowpath.pipes') ?? 'Pipes'}</dt><dd><RollingNumber value={details.summary.pipe_count} format={(n) => metric(n, 0)} /></dd></div>
                <div><dt>{t('flowpath.sections') ?? 'Sections'}</dt><dd><RollingNumber value={details.summary.segment_count} format={(n) => metric(n, 0)} /></dd></div>
                <div><dt>{t('flowpath.length') ?? 'Length'}</dt><dd><RollingNumber value={details.summary.total_length_m} format={(n) => `${metric(n)} m`} /></dd></div>
                <div><dt>{t('flowpath.volume') ?? 'Volume'}</dt><dd><RollingNumber value={details.summary.total_volume_m3 * 1000} format={(n) => `${metric(n, 1)} L`} /></dd></div>
                <div><dt>{t('flowpath.diameter') ?? 'Diameter'}</dt><dd>{diameterRange(details, t)}</dd></div>
              </dl>
              {selected && (
                <section className="flowpath-section-card" aria-label={t('flowpath.selectedSection', { index: selected.section_index }) ?? `Selected section ${selected.section_index}`}>
                  <p>{t('flowpath.sectionHeading', { index: selected.section_index }) ?? `SECTION ${selected.section_index}`} <span>{t('flowpath.localIndex', { index: selected.pipe_section_index }) ?? `local ${selected.pipe_section_index}`}</span></p>
                  <strong>{selected.pipe_label}</strong>
                  <dl>
                    <div><dt>{t('flowpath.length') ?? 'Length'}</dt><dd>{metric(selected.length_m, 3)} m</dd></div>
                    <div><dt>{t('flowpath.diameter') ?? 'Diameter'}</dt><dd>{metric(selected.diameter_m * 1000, 1)} mm</dd></div>
                    <div><dt>{t('flowpath.start') ?? 'Start'}</dt><dd>{point(selected.start, t)}</dd></div>
                    <div><dt>{t('flowpath.center') ?? 'Center'}</dt><dd>{point(selected.center, t)}</dd></div>
                    <div><dt>{t('flowpath.end') ?? 'End'}</dt><dd>{point(selected.end, t)}</dd></div>
                  </dl>
                </section>
              )}
              <ol className="topo-pipe-list" aria-label={t('flowpath.pipeGeometryAria', { label }) ?? `${label} pipe geometry`}>
                {details.pipes.map((pipe) => (
                  <li key={`${pipe.label}:${pipe.section_range.join('-')}`}>
                    <strong>{pipe.label}</strong>
                    <span>{pipe.nsegment} {pipe.nsegment === 1 ? t('flowpath.sectionOne') ?? 'section' : t('flowpath.sectionOther') ?? 'sections'} · Ø{metric(pipe.diameter_m * 1000, 1)} {t('flowpath.mmUnit') ?? 'mm'} · {metric(pipe.total_length_m)} m</span>
                    <small>{t('flowpath.globalSections', { from: pipe.section_range[0], to: pipe.section_range[1] }) ?? `global sections ${pipe.section_range[0]}–${pipe.section_range[1]}`}</small>
                  </li>
                ))}
              </ol>
              <p className="topo-detail-note">{t('flowpath.geometryAcceptanceNote') ?? 'Endpoint-constrained parsed geometry; no engineering acceptance is inferred.'}</p>
            </details>
          </aside>
        </div>
      )}
    </section>
  );
}
