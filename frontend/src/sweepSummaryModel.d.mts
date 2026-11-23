import type { SweepSummaryCell, SweepSummaryRow } from './sweepApi';
export type SummarySort = 'case' | 'PT' | 'TM' | 'HOL' | 'LIQC';
export declare const SUMMARY_VARIABLES: readonly ('PT' | 'TM' | 'HOL' | 'LIQC')[];
export declare function sortSummaryRows(rows: readonly SweepSummaryRow[], sortBy: SummarySort): SweepSummaryRow[];
export declare function sweepReasonText(code: string | null | undefined, t: (key: string) => string): string;
export declare function formatChange(cell: SweepSummaryCell | undefined, isBase: boolean): string | null;
