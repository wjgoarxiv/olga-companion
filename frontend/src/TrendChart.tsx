import { useMemo, useRef, useState } from 'react';
import { buildTrendGeometry, clientToDataX, createInspectionNavigation, createNearestPointLookup, finiteSampleOrdinal, transitionInspection, niceTicks, ticksWithin } from './trendGeometry';
import { useLocale } from './i18n/index.ts';
import { formatUnit } from './formatUnit';
import { useSignificantFigures } from './useSignificantFigures';
import { metric } from './resultPresentation';
import { formatDistinctTicks } from './significantFigures.mjs';
import type { Series } from './session';

/* Single-series trend: nice ticks, hover crosshair with a unit readout,
 * drag-to-brush zoom, draw-in on mount, full keyboard inspection. */

export default function TrendChart({
  series,
  overlays = [],
  unit,
  onBrushRange,
}: {
  readonly series: Series;
  readonly overlays?: readonly { readonly key: string; readonly series: Series; readonly color: string }[];
  readonly unit?: string;
  readonly onBrushRange?: (start: number, end: number) => void;
}) {
  const { t } = useLocale();
  const significantFigures = useSignificantFigures();
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [cross, setCross] = useState<{ x: number; index: number } | null>(null);
  const [brush, setBrush] = useState<{ x0: number; x1: number } | null>(null);
  const dragStart = useRef<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const geometry = useMemo(() => {
    const time = series.time;
    return buildTrendGeometry(time, series.values, { width: 508, height: 352, pointBudget: 508 });
  }, [series]);
  const navigation = useMemo(() => createInspectionNavigation(series.time, series.values), [series]);
  const nearestLookup = useMemo(() => createNearestPointLookup(series.time, series.values), [series]);
  const titleId = `trend-title-${series.time.length}-${series.values.length}`;
  const descId = `trend-desc-${series.time.length}-${series.values.length}`;
  const [xMin, xMax] = geometry.xDomain ?? [0, 1];
  const [yMin, yMax] = geometry.yDomain ?? [0, 1];
  const overlayPaths = useMemo(() => overlays.map((overlay) => {
    const time = overlay.series.time;
    const pairs = time.map((value, index) => ({ time: value, value: overlay.series.values[index] }))
      .filter((pair) => Number.isFinite(pair.time) && Number.isFinite(pair.value));
    if (pairs.length === 0 || xMax === xMin || yMax === yMin) return { key: overlay.key, d: '', color: overlay.color };
    const step = pairs.length > 1 ? Math.max(1, Math.floor(pairs.length / 264)) : 1;
    const kept = pairs.filter((_, index) => index % step === 0);
    const d = kept.map((pair, index) => {
      const x = 76 + ((pair.time - xMin) / (xMax - xMin)) * 508;
      const y = 24 + 352 - ((pair.value - yMin) / (yMax - yMin)) * 352;
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
    return { key: overlay.key, d, color: overlay.color };
  }), [overlays, xMin, xMax, yMin, yMax]);
  const xTicks = useMemo(() => ticksWithin(niceTicks(xMin, xMax, 6), xMin, xMax), [xMin, xMax]);
  const yTicks = useMemo(() => ticksWithin(niceTicks(yMin, yMax, 5), yMin, yMax), [yMin, yMax]);
  const xLabels = useMemo(() => formatDistinctTicks(xTicks, significantFigures), [xTicks, significantFigures]);
  const yLabels = useMemo(() => formatDistinctTicks(yTicks, significantFigures), [yTicks, significantFigures]);
  const shownUnit = unit ?? series.unit ?? '';
  const unitSuffix = shownUnit ? ` ${formatUnit(shownUnit)}` : '';

  function dataToPixelX(time: number): number {
    if (xMax === xMin) return 76 + 508 / 2;
    return 76 + ((time - xMin) / (xMax - xMin)) * 508;
  }

  function pixelToData(clientX: number): number {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return xMin;
    return clientToDataX(clientX, rect.left, rect.width, rect.height, xMin, xMax);
  }

  function commitBrush(clientX: number) {
    const start = dragStart.current;
    dragStart.current = null;
    if (start === null) return;
    const end = pixelToData(clientX);
    const span = Math.abs(end - start);
    setBrush(null);
    if (span > (xMax - xMin) * 0.02 && span > 0) {
      onBrushRange?.(Math.min(start, end), Math.max(start, end));
    }
  }

  const readout = cross !== null && geometry.points.length > 0
    ? (() => {
      const point = geometry.points.find((candidate) => candidate.index === cross.index) ?? geometry.points[0];
      return { x: dataToPixelX(point.time), time: point.time, value: point.value };
    })()
    : null;

  return (
    <div className="trend-wrap">
      <div className="trend-viewport">
      <svg
        ref={svgRef}
        className="trend-svg"
        viewBox="0 0 640 400"
        preserveAspectRatio="xMidYMid meet"
        tabIndex={0}
        aria-labelledby={`${titleId} ${descId}`}
        onKeyDown={(event) => {
          const next = transitionInspection(event.key, activeIndex, navigation);
          if (!next.handled) return;
          event.preventDefault();
          if (typeof next.nextIndex === 'number') {
            setActiveIndex(next.nextIndex);
            setCross({ x: 0, index: next.nextIndex });
          } else {
            setActiveIndex(null);
            setCross(null);
          }
        }}
        onMouseMove={(event) => {
          if (dragStart.current !== null) {
            const rect = svgRef.current?.getBoundingClientRect();
            if (rect) {
              setBrush({ x0: dragStart.current, x1: clientToDataX(event.clientX, rect.left, rect.width, rect.height, xMin, xMax) });
            }
            return;
          }
          const time = pixelToData(event.clientX);
          const index = nearestLookup.find(time);
          if (index !== null) {
            setActiveIndex(index);
            setCross({ x: 0, index });
          }
        }}
        onMouseLeave={() => { setCross(null); setBrush(null); dragStart.current = null; }}
        onMouseDown={(event) => { dragStart.current = pixelToData(event.clientX); }}
        onMouseUp={(event) => commitBrush(event.clientX)}
      >
        <title id={titleId}>{t('results.trendTitle')}</title>
        <desc id={descId}>{t('results.trendDesc', { points: geometry.finiteCount })}</desc>
        {yTicks.map((tick, tickIndex) => {
          const y = 24 + 352 - ((tick - yMin) / (yMax - yMin || 1)) * 352;
          return (
            <g key={tick}>
              <line x1={76} y1={y} x2={584} y2={y} className="trend-grid" />
              <text x={70} y={y + 4} textAnchor="end" className="trend-tick">{yLabels[tickIndex]}</text>
            </g>
          );
        })}
        {xTicks.map((tick, index) => (
          <text key={tick} x={dataToPixelX(tick)} y={392} textAnchor={index === xTicks.length - 1 ? 'end' : 'middle'} className="trend-tick">{xLabels[index]}</text>
        ))}
        {brush !== null && (
          <rect
            x={dataToPixelX(Math.min(brush.x0, brush.x1))}
            y={12}
            width={Math.abs(dataToPixelX(brush.x1) - dataToPixelX(brush.x0))}
            height={364}
            className="trend-brush"
          />
        )}
        <path d={geometry.path} transform="translate(76 24)" className="trend-line trend-draw" pathLength={1} fill="none" />
        {overlayPaths.map((overlay) => overlay.d !== '' && (
          <path key={overlay.key} d={overlay.d} fill="none" stroke={overlay.color} strokeWidth={2} />
        ))}
        {activeIndex !== null && (() => {
          const point = geometry.points.find((candidate) => candidate.index === activeIndex);
          return point ? <circle cx={76 + point.x} cy={24 + point.y} r={5} className="trend-inspect" /> : null;
        })()}
        {cross !== null && readout !== null && (
          <line x1={0} y1={12} x2={0} y2={376} className="trend-crosshair" style={{ transform: `translateX(${readout.x}px)` }} />
        )}
      </svg>
      </div>
      {readout !== null && (
        <div
          className="trend-readout"
          role="status"
          aria-live="polite"
          style={{ transform: `translate(${Math.min(Math.max(readout.x, 8), 480)}px, 0)` }}
        >
          {t('results.readout', { time: String(readout.time), value: `${metric(readout.value, significantFigures)}${unitSuffix}` })}
        </div>
      )}
      <p className="trend-live" aria-live="polite">
        {activeIndex === null ? '' : `${finiteSampleOrdinal(activeIndex, navigation)} / ${geometry.finiteCount}`}
      </p>
    </div>
  );
}
