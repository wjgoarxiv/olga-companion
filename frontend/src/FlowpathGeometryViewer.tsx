import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from 'react';
import { buildFlowpathProjection, defaultFlowpathView, transitionSectionSelection, type FlowpathView } from './flowpathGeometry';
import { useLocale } from './i18n/index.ts';
import type { FlowpathSection } from './workspaceApi';

/* Drawing size before the plot is measured; afterwards one SVG unit is one screen pixel,
   so the chart fills its pane and labels keep their intended size at any panel width. */
const DEFAULT_SIZE = { width: 960, height: 560 };
const MIN_SIDE = 160;
/* Palette lives in base.css as --pipe-1..7 (with dark-scheme values); these
   references resolve per-scheme through inline style, never as paint attributes. */
const PIPE_COLORS = ['var(--pipe-1)', 'var(--pipe-2)', 'var(--pipe-3)', 'var(--pipe-4)', 'var(--pipe-5)', 'var(--pipe-6)', 'var(--pipe-7)'];

type Camera = { x: number; y: number; scale: number };
type Drag = { pointerId: number; x: number; y: number; cameraX: number; cameraY: number };

function clampScale(scale: number) {
  return Math.min(6, Math.max(0.65, scale));
}

export type FlowpathGeometryViewerProps = {
  readonly sections: FlowpathSection[];
  readonly selectedIndex: number | null;
  readonly onSelect: (sectionIndex: number | null) => void;
  /** Length-and-elevation data has no plan coordinates, so only the elevation profile is honest. */
  readonly profileOnly?: boolean;
};

export default function FlowpathGeometryViewer({ sections, selectedIndex, onSelect, profileOnly = false }: FlowpathGeometryViewerProps) {
  const [view, setView] = useState<FlowpathView>(() => (profileOnly ? 'elevation' : defaultFlowpathView(sections)));
  const [exaggeration, setExaggeration] = useState(1);
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, scale: 1 });
  const [hovered, setHovered] = useState<number | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const plotRef = useRef<SVGSVGElement | null>(null);
  const [size, setSize] = useState(DEFAULT_SIZE);
  const { width: plotWidth, height: plotHeight } = size;
  const projection = useMemo(() => buildFlowpathProjection(sections, {
    view, width: plotWidth, height: plotHeight, padding: 56, elevationExaggeration: exaggeration,
  }), [sections, view, exaggeration, plotWidth, plotHeight]);
  const pipeColors = useMemo(() => new Map(
    [...new Set(sections.map((section) => section.pipe_label))]
      .map((label, index) => [label, PIPE_COLORS[index % PIPE_COLORS.length]]),
  ), [sections]);
  const labels = useMemo(() => [...pipeColors.keys()].map((label, index) => {
    const matches = projection.segments.filter((segment) => segment.pipe_label === label);
    return { label, point: matches[Math.floor(matches.length / 2)]?.center, offset: 12 + ((index % 3) * 13) };
  }), [pipeColors, projection]);

  useLayoutEffect(() => {
    const element = plotRef.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      const width = Math.round(rect.width);
      const height = Math.round(rect.height);
      if (width < MIN_SIDE || height < MIN_SIDE) return;
      setSize((current) => (current.width === width && current.height === height ? current : { width, height }));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setView(profileOnly ? 'elevation' : defaultFlowpathView(sections));
    setExaggeration(1);
  }, [sections, profileOnly]);

  useEffect(() => {
    setCamera({ x: 0, y: 0, scale: 1 });
    onSelect(null);
  }, [view, exaggeration, sections, onSelect]);

  function selectView(nextView: FlowpathView) {
    setView(nextView);
  }

  function handleKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    const transition = transitionSectionSelection(event.key, selectedIndex, sections.length);
    if (!transition.handled) return;
    event.preventDefault();
    onSelect(transition.nextIndex);
  }

  function handleWheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    setCamera((current) => ({ ...current, scale: clampScale(current.scale * factor) }));
  }

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      cameraX: camera.x, cameraY: camera.y,
    };
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    setCamera((current) => ({
      ...current,
      x: drag.cameraX + (((event.clientX - drag.x) / rect.width) * plotWidth / current.scale),
      y: drag.cameraY + (((event.clientY - drag.y) / rect.height) * plotHeight / current.scale),
    }));
  }

  function handlePointerEnd(event: PointerEvent<SVGSVGElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  const activeIndex = hovered ?? selectedIndex;
  const active = activeIndex == null ? null : sections[activeIndex];
  const { t } = useLocale();
  const viewLabelKey = {
    plan: 'flowpath.view.plan', elevation: 'flowpath.view.elevation', side: 'flowpath.view.side', isometric: 'flowpath.view.isometric',
  } as const;
  const viewWord = t(viewLabelKey[view]);
  return (
    <div className="flowpath-viewer">
      <div className="flowpath-toolbar" aria-label={t('flowpath.controlsAria')}>
        {profileOnly ? (
          <span className="flowpath-profile-badge" data-testid="flowpath-profile-badge">{t('flowpath.profileBadge')}</span>
        ) : (
          <div className="flowpath-view-switch" role="group" aria-label={t('flowpath.projection')}>
            {(['plan', 'elevation', 'side', 'isometric'] as FlowpathView[]).map((option) => (
              <button key={option} type="button" className={view === option ? 'active' : ''} aria-pressed={view === option} onClick={() => selectView(option)}>
                {t(viewLabelKey[option])}
              </button>
            ))}
          </div>
        )}
        {(view === 'elevation' || view === 'side') && (
          <label><span className="flowpath-exaggeration-text">{t('flowpath.elevation')}</span> <select aria-label={t('flowpath.elevationAria')} value={exaggeration} onChange={(event) => setExaggeration(Number(event.target.value))}>
            {[1, 2, 5, 10].map((value) => <option key={value} value={value}>{value}×</option>)}
          </select></label>
        )}
        <div className="flowpath-camera-controls" role="group" aria-label={t('flowpath.cameraAria')}>
          <button type="button" aria-label={t('flowpath.zoomOut')} onClick={() => setCamera((current) => ({ ...current, scale: clampScale(current.scale / 1.2) }))}>−</button>
          <button type="button" aria-label={t('flowpath.fitView')} onClick={() => setCamera({ x: 0, y: 0, scale: 1 })}>{t('flowpath.fit')}</button>
          <button type="button" aria-label={t('flowpath.zoomIn')} onClick={() => setCamera((current) => ({ ...current, scale: clampScale(current.scale * 1.2) }))}>+</button>
        </div>
      </div>
      <ul className="flowpath-pipe-legend" aria-label={t('flowpath.legend')}>
        {[...pipeColors.entries()].map(([label, color]) => (
          <li key={label}><span style={{ backgroundColor: color }} aria-hidden="true" />{label}</li>
        ))}
      </ul>
      <div className="flowpath-plot-shell">
        <svg
          ref={plotRef}
          className="flowpath-plot"
          viewBox={`0 0 ${plotWidth} ${plotHeight}`}
          role="application"
          aria-label={t('flowpath.svgAria', { view: viewWord })}
          tabIndex={0}
          onKeyDown={handleKeyDown}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
        >
          <g transform={`translate(${camera.x} ${camera.y}) scale(${camera.scale})`}>
            {projection.segments.map((segment) => {
              const selected = selectedIndex === segment.section_index;
              const highlighted = activeIndex === segment.section_index;
              const width = Math.min(12, Math.max(5, segment.diameter_m * 110));
              const collapsed = Math.hypot(segment.end.x - segment.start.x, segment.end.y - segment.start.y) < 2;
              const sectionLabel = t('flowpath.sectionAria', { index: segment.section_index, label: segment.pipe_label, length: segment.length_m.toFixed(3) }) ?? `Section ${segment.section_index}, ${segment.pipe_label}, ${segment.length_m.toFixed(3)} metres`;
              return (
                <g key={segment.section_index} className={`flowpath-section${selected ? ' selected' : ''}${highlighted ? ' highlighted' : ''}`}>
                  {collapsed ? (
                    <circle className="flowpath-section-hit" data-section-index={segment.section_index} aria-label={sectionLabel} cx={segment.start.x} cy={segment.start.y} r={12} onClick={(event) => { event.stopPropagation(); onSelect(segment.section_index); }} onPointerEnter={() => setHovered(segment.section_index)} onPointerLeave={() => setHovered(null)} />
                  ) : (
                    <path className="flowpath-section-hit" data-section-index={segment.section_index} aria-label={sectionLabel} d={`M${segment.start.x},${segment.start.y} L${segment.end.x},${segment.end.y}`} onClick={(event) => { event.stopPropagation(); onSelect(segment.section_index); }} onPointerEnter={() => setHovered(segment.section_index)} onPointerLeave={() => setHovered(null)} />
                  )}
                  <path className="flowpath-section-line" d={`M${segment.start.x},${segment.start.y} L${segment.end.x},${segment.end.y}`} style={{ stroke: pipeColors.get(segment.pipe_label) }} strokeWidth={width} vectorEffect="non-scaling-stroke" />
                  <circle className="flowpath-boundary" cx={segment.start.x} cy={segment.start.y} r={3.4} vectorEffect="non-scaling-stroke" />
                </g>
              );
            })}
            {projection.segments.length > 0 && <circle className="flowpath-boundary endpoint" cx={projection.segments[projection.segments.length - 1].end.x} cy={projection.segments[projection.segments.length - 1].end.y} r={4.2} />}
            {labels.map(({ label, point, offset }) => point && <text key={label} className="flowpath-pipe-label" x={point.x} y={point.y - offset} textAnchor="middle">{label}</text>)}
          </g>
        </svg>
        <p className="flowpath-axis-caption">{profileOnly ? t('flowpath.profileCaption', { exaggeration }) : view === 'plan' ? t('flowpath.viewPlanCaption') ?? 'X–Z plan' : view === 'elevation' ? t('flowpath.viewElevationCaption', { exaggeration }) ?? `Across: distance along the pipe · Up: height (y) · ${exaggeration}×` : view === 'side' ? t('flowpath.viewSideCaption', { exaggeration }) ?? `Across: horizontal distance from the start · Up: height (y) · ${exaggeration}×` : t('flowpath.viewIsoCaption') ?? 'X / Y / Z isometric'}</p>
        {active && <p className="flowpath-hover-readout">{t('flowpath.hoverReadout', { index: active.section_index, label: active.pipe_label, local: active.pipe_section_index, length: active.length_m.toFixed(3) }) ?? `SECTION ${active.section_index} · ${active.pipe_label} / local ${active.pipe_section_index} · ${active.length_m.toFixed(3)} m`}</p>}
      </div>
      <p className="ui-visually-hidden" aria-live="polite">{active ? t('flowpath.liveSection', { index: active.section_index, label: active.pipe_label, length: active.length_m.toFixed(3) }) ?? `Section ${active.section_index}, ${active.pipe_label}, length ${active.length_m.toFixed(3)} metres` : t('flowpath.liveNone') ?? 'No section selected'}</p>
      {profileOnly && <p className="flowpath-keyboard-hint" data-testid="flowpath-profile-note">{t('flowpath.profileNote')}</p>}
      <p className="flowpath-keyboard-hint">{t('flowpath.hint')}</p>
    </div>
  );
}
