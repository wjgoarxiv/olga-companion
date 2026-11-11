import { useMemo, useRef, useState } from 'react';
import { metric, presentSeriesTable, seriesFigures, seriesTableUnits, seriesTableWindow, SERIES_TABLE_ROW_HEIGHT } from './resultPresentation';
import { useLocale } from './i18n/index.ts';
import { useSignificantFigures } from './useSignificantFigures';
import { formatUnit } from './formatUnit';

/** Swap a presenter's raw-unit suffix for the formatted unit, exactly once. */
export function displayHeader(header: string, rawUnit: string): string {
  const formatted = formatUnit(rawUnit);
  if (rawUnit && header.endsWith(` (${rawUnit})`)) {
    return `${header.slice(0, header.length - rawUnit.length - 3)} (${formatted})`;
  }
  return formatted ? `${header} (${formatted})` : header;
}

export default function SeriesTable({ receipt }: { readonly receipt: unknown }) {
  const significantFigures = useSignificantFigures();
  const { t } = useLocale();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(360);
  const table = useMemo(() => presentSeriesTable(receipt, significantFigures, t), [receipt, significantFigures, t]);
  const valueFigures = useMemo(() => seriesFigures(receipt, significantFigures), [receipt, significantFigures]);
  const window = useMemo(
    () => seriesTableWindow(table?.rows.length ?? 0, scrollTop, viewportHeight),
    [table, scrollTop, viewportHeight],
  );
  if (!table) return <p className="error">{t('series.unavailable')}</p>;
  const visibleRows = table.rows.slice(window.start, window.end);
  const rawUnits = seriesTableUnits(receipt);
  // The presenter headers pin the raw codes; swap the raw suffix for the
  // formatted unit so each header names its unit exactly once.
  const timeHeader = displayHeader(table.time_header, rawUnits.time);
  const valueHeader = displayHeader(table.value_header, rawUnits.value);
  return (
    <section className="evidence-series rv-series-table" aria-label={table.caption}>
      <div
        className="evidence-table-viewport"
        ref={viewportRef}
        tabIndex={0}
        role="region"
        aria-label={table.caption}
        aria-rowcount={table.rows.length}
        onScroll={(event) => {
          const target = event.currentTarget;
          setScrollTop(target.scrollTop);
          if (target.clientHeight !== viewportHeight) setViewportHeight(target.clientHeight);
        }}
      >
        <table>
          <caption>{table.caption}</caption>
          <thead>
            <tr>
              <th scope="col">{timeHeader}</th>
              <th scope="col">{valueHeader}</th>
            </tr>
          </thead>
          <tbody>
            {window.topSpacer > 0 && (
              <tr aria-hidden="true"><td colSpan={2} style={{ height: window.topSpacer, padding: 0, border: 0 }} /></tr>
            )}
            {visibleRows.map((row, index) => (
              <tr key={`${row.time}:${window.start + index}`} style={{ height: SERIES_TABLE_ROW_HEIGHT }}>
                <td>{metric(row.time, significantFigures)}</td>
                <td>{metric(row.value, valueFigures)}</td>
              </tr>
            ))}
            {window.bottomSpacer > 0 && (
              <tr aria-hidden="true"><td colSpan={2} style={{ height: window.bottomSpacer, padding: 0, border: 0 }} /></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="evidence-series-summary">
        {table.row_summary}{table.truncated ? t('series.rangeNote') ?? ' · Additional rows remain available by range.' : ''}
      </p>
      {table.analysis_summary && <p className="evidence-series-analysis">{table.analysis_summary}</p>}
    </section>
  );
}
