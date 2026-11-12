import type { ReactNode } from 'react';
import type { SweepSummaryRow } from './sweepApi';
import { useLocale } from './i18n/index.ts';
import { Table } from './ui/Table';

const SUMMARY_COLUMNS = ['PT', 'TM', 'HOL', 'LIQC'] as const;

function formatParam(param: Record<string, unknown>): string {
  const path = typeof param.path === 'string' ? param.path : null;
  const value = param.value;
  if (path) return `${path} = ${String(value)}`;
  return JSON.stringify(param);
}

export default function SweepSummaryTable({ rows }: { readonly rows: readonly SweepSummaryRow[] }) {
  const { t } = useLocale();
  return (
    <div className="sweep-summary-wrap">
      <Table
        ariaLabel={t('sweep.summaryAria')}
        columns={[
          { key: 'case', header: t('sweep.colCase') },
          { key: 'params', header: t('sweep.colParams') },
          { key: 'run', header: t('sweep.colRun') },
          ...SUMMARY_COLUMNS.map((variable) => ({ key: variable, header: variable })),
        ]}
        rows={rows.map((row) => {
          const cells: Record<string, ReactNode> = {
            case: t('run.sweepCase', { index: String(row.index + 1).padStart(2, '0') }),
            params: row.params.length > 0 ? row.params.map(formatParam).join('; ') : '—',
            run: row.run_id ? `${row.state}` : row.state,
          };
          for (const variable of SUMMARY_COLUMNS) {
            const cell = row.outputs[variable];
            cells[variable] = !cell || cell.value == null
              ? <span className="sweep-summary-null" title={cell?.reason ?? t('sweep.noValue') ?? 'no value'}>—</span>
              : `${cell.value}${cell.unit ? ` ${cell.unit}` : ''}`;
          }
          return cells;
        })}
      />
    </div>
  );
}
