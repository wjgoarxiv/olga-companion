type PanelItem = { readonly key: string; readonly series: { readonly unit?: string | null; readonly time: readonly number[] } };
export type TrendPanel<T extends PanelItem> = { readonly key: string; readonly primary: T; readonly overlays: readonly T[] };

export function trendPanels<T extends PanelItem>(plotted: readonly T[], activeKey: string | null, oneAxis: boolean): TrendPanel<T>[];
export function panelSeriesNames(items: readonly { readonly variable: { readonly variable: string; readonly position?: string | null }; readonly source?: string | null }[]): string;
export function sharedTimeSpan<T extends PanelItem>(plotted: readonly T[]): [number, number] | null;
