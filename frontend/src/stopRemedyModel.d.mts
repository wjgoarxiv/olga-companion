export type StopRemedyAnswer = { readonly rel: string | null; readonly row_id: string | null; readonly reason_key: string };
export declare const REMEDY_REASONS: readonly string[];
export declare function openStopRemedy(
  runId: string,
  deps: {
    readonly get: (url: string) => Promise<StopRemedyAnswer>;
    readonly activeCase?: string | null;
    readonly open: (rel: string, rowId: string) => void;
  },
): Promise<{ reasonKey: string | null }>;
