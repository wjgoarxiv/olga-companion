import { useMemo, useState } from 'react';
import TrendChart from './TrendChart';
import { useLocale } from './i18n/index.ts';
import { formatUnit } from './formatUnit';
import { sharedTimeSpan, trendPanels } from './trendPanels.mjs';
import type { Series } from './session';

type Plotted = { readonly key: string; readonly series: Series; readonly color: string; readonly variable: { readonly variable: string } };

/* One chart per displayed unit on a shared time axis, so a 0–1 signal is not flattened next to a
 * pressure. The first panel holds the active series and takes the zoom; "one axis" restores the
 * single overlaid chart. */
export default function TrendChartStack({
  plotted,
  activeKey,
  activeUnit,
  rangeKey,
  onBrushRange,
}: {
  readonly plotted: readonly Plotted[];
  readonly activeKey: string | null;
  readonly activeUnit?: string;
  readonly rangeKey: string;
  readonly onBrushRange: (start: number, end: number) => void;
}) {
  const { t } = useLocale();
  const [oneAxis, setOneAxis] = useState(false);
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const unitGroups = useMemo(() => trendPanels(plotted, activeKey, false).length, [plotted, activeKey]);
  const panels = useMemo(() => trendPanels(plotted, activeKey, oneAxis), [plotted, activeKey, oneAxis]);
  const timeSpan = useMemo(() => sharedTimeSpan(plotted), [plotted]);
  const stacked = panels.length > 1;
  const names = (panel: (typeof panels)[number]) => [panel.primary, ...panel.overlays].map((item) => item.variable.variable).join(', ');

  return (
    <>
      {panels.map((panel, index) => (
        <section key={panel.key} className="rv-chart-panel" aria-label={t('results.panelLabel', { names: names(panel), unit: formatUnit(panel.primary.series.unit || '') || '—' })}>
          {index > 0 && (
            <p className="rv-chart-panel-title">
              {names(panel)}{panel.primary.series.unit ? ` (${formatUnit(panel.primary.series.unit)})` : ''}
            </p>
          )}
          <TrendChart
            key={`${panel.key}:${rangeKey}`}
            series={panel.primary.series}
            overlays={panel.overlays.map((item) => ({ key: item.key, series: item.series, color: item.color }))}
            unit={(index === 0 ? activeUnit : panel.primary.series.unit) ?? undefined}
            onBrushRange={index === 0 ? onBrushRange : undefined}
            timeSpan={stacked ? timeSpan : null}
            hoverTime={stacked ? hoverTime : null}
            onHoverTime={stacked ? setHoverTime : undefined}
          />
        </section>
      ))}
      {unitGroups > 1 && (
        <label className="rv-one-axis">
          <input type="checkbox" checked={oneAxis} onChange={(event) => setOneAxis(event.target.checked)} />
          {t('results.oneAxis')}
        </label>
      )}
    </>
  );
}
