export type PreflightItem = {
  readonly id: string;
  readonly state: 'ok' | 'warn' | 'missing' | string;
  readonly message_code: string;
  readonly row_id?: string;
  readonly target?: string;
  readonly field?: string;
  readonly detail?: string;
  readonly values?: Readonly<Record<string, string | number>>;
};

export function orderedItems(items: readonly PreflightItem[]): PreflightItem[];
export function rowOpener(rel: string, item: PreflightItem, open: (rel: string, rowId: string) => void): (() => void) | null;
