import { useState, type ReactNode } from 'react';
import type { SweepSummaryRow } from './sweepApi';
import { useLocale } from './i18n/index.ts';
import { Table } from './ui/Table';
import { formatSweepState } from './RunSweepStatus';
import { SUMMARY_VARIABLES, formatChange, sortSummaryRows, type SummarySort } from './sweepSummaryModel.mjs';

function formatParam(param: Record<string, unknown>): string {
  const path = typeof param.path === 'string' ? param.path : null;
  const value = param.value;
  if (path) return `${path} = ${String(value)}`;
  // The sweep plan's own shape: { keyword, key, value, label }.
  if (typeof param.keyword === 'string' && typeof param.key === 'string') {
    const label = typeof param.label === 'string' && param.label ? ` (${param.label})` : '';
    return `${param.keyword}.${param.key}${label} = ${String(value)}`;
  }
  return JSON.stringify(param);
}

export default function SweepSummaryTable({ rows, initialSort = 'case' }: { readonly rows: readonly SweepSummaryRow[]; readonly initialSort?: SummarySort }) {
  const { t } = useLocale();
  const [sortBy, setSortBy] = useState<SummarySort>(initialSort);
  // Re-ordered rows are announced only after the user changes the order, not on first render.
  const [sortedByUser, setSortedByUser] = useState(false);
  const orderLabel = sortBy === 'case' ? t('sweep.sortCase') : t('sweep.sortChange', { variable: sortBy });
  const baseIndex = rows[0]?.index;
  return (
    <div className="sweep-summary-wrap">
      <label className="sweep-summary-sort">
        <span>{t('sweep.sortBy')}</span>
        <select value={sortBy} onChange={(event) => { setSortBy(event.target.value as SummarySort); setSortedByUser(true); }}>
          <option value="case">{t('sweep.sortCase')}</option>
          {SUMMARY_VARIABLES.map((variable) => <option key={variable} value={variable}>{t('sweep.sortChange', { variable })}</option>)}
        </select>
      </label>
      <p className="ui-visually-hidden" role="status">{sortedByUser ? t('sweep.sortedBy', { order: orderLabel }) : null}</p>
      <Table
        ariaLabel={t('sweep.summaryAria')}
        columns={[
          { key: 'case', header: t('sweep.colCase') },
          { key: 'params', header: t('sweep.colParams') },
          { key: 'run', header: t('sweep.colRun') },
          ...SUMMARY_VARIABLES.map((variable) => ({ key: variable, header: variable })),
        ]}
        rows={sortSummaryRows(rows, sortBy).map((row) => {
          const isBase = row.index === baseIndex;
          const caseLabel = t('run.sweepCase', { index: String(row.index + 1).padStart(2, '0') });
          const cells: Record<string, ReactNode> = {
            case: isBase ? <span>{caseLabel}<small className="sweep-summary-base">{t('sweep.baseCase')}</small></span> : caseLabel,
            params: row.params.length !== 0 ? row.params.map(formatParam).join('; ') : '—',
            run: formatSweepState(row.state, t),
          };
          for (const variable of SUMMARY_VARIABLES) {
            const cell = row.outputs[variable];
            const change = formatChange(cell, isBase);
            cells[variable] = !cell || cell.value == null
              ? (
                <span className="sweep-summary-null" title={cell?.reason ?? t('sweep.noValue')}>
                  <span aria-hidden="true">—</span>
                  <span className="ui-visually-hidden">{cell?.reason ? `${t('sweep.noValue')}: ${cell.reason}` : t('sweep.noValue')}</span>
                </span>
              )
              : (
                <span>
                  {`${cell.value}${cell.unit ? ` ${cell.unit}` : ''}`}
                  {change && <small className="sweep-summary-change">{t('sweep.changeFromBase', { change })}</small>}
                  {!isBase && !change && cell.change_reason && <small className="sweep-summary-change" title={cell.change_reason}>{t('sweep.noChange')}<span className="ui-visually-hidden">: {cell.change_reason}</span></small>}
                </span>
              );
          }
          return cells;
        })}
      />
    </div>
  );
}
