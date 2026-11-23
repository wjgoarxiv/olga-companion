import { useLocale } from './i18n/index.ts';
import { formatUnit } from './formatUnit';
import { metric } from './resultPresentation';
import { useSignificantFigures } from './useSignificantFigures';
import { figuresForSpan } from './significantFigures.mjs';
import type { Series } from './session';

/** Rows the table shows at most; the CSV export carries the whole series. */
export const TABLE_ROW_CAP = 1000;

/** The chart's samples as a table: time and value, one row per sample (0.1.20 row 10). */
export function TrendDataTable({ series, unit, id }: { readonly series: Series; readonly unit?: string; readonly id: string }) {
  const { t, locale } = useLocale();
  const significantFigures = useSignificantFigures();
  const total = Math.min(series.time.length, series.values.length);
  const shown = Math.min(total, TABLE_ROW_CAP);
  // The same unit the chart shows: the (possibly converted) series first, the file unit after.
  const valueUnit = series.unit || unit || '';
  // Like the chart: enough figures that neighbouring samples read differently.
  const figuresFor = (values: readonly number[]) => {
    const finite = values.slice(0, shown).filter(Number.isFinite);
    return finite.length === 0 ? significantFigures : figuresForSpan(Math.min(...finite), Math.max(...finite), significantFigures);
  };
  const timeFigures = figuresFor(series.time);
  const valueFigures = figuresFor(series.values);
  const cell = (value: number, figures: number) => (Number.isFinite(value) ? metric(value, figures) : '—');
  return (
    <div id={id} className="trend-table-wrap" role="region" tabIndex={0} aria-labelledby={`${id}-caption`}>
      <table className="ui-table trend-table">
        <caption id={`${id}-caption`} className="ui-table-caption">
          {t('results.table.caption', { series: [series.variable, series.position].filter(Boolean).join(' '), count: total.toLocaleString(locale) })}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t('results.table.time', { unit: formatUnit(series.time_unit || 's') })}</th>
            <th scope="col" className="ui-num">{valueUnit ? `${series.variable} (${formatUnit(valueUnit)})` : series.variable}</th>
          </tr>
        </thead>
        <tbody>
          {series.time.slice(0, shown).map((time, index) => (
            <tr key={index}>
              <th scope="row">{cell(time, timeFigures)}</th>
              <td className="ui-num">{cell(series.values[index], valueFigures)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > shown && <p className="trend-table-more">{t('results.table.more', { shown, total })}</p>}
    </div>
  );
}
