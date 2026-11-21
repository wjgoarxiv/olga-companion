export type StopReason = {
  readonly code: string;
  readonly stopped_at_s?: number | null;
  readonly pressure_bara?: number | null;
  readonly temperature_c?: number | null;
  readonly where?: string | null;
  readonly exit_code?: number | null;
  readonly exit_message?: string | null;
  readonly last_lines?: readonly string[];
  /** The OLGA line the cause was read from, paths removed. */
  readonly evidence?: string | null;
  /** The place OLGA named, only when it is clearly a node, a pipe section or an input key. */
  readonly pointer?: StopPointer | null;
};
export type StopPointer =
  | { readonly kind: 'node'; readonly label: string }
  | { readonly kind: 'pipe'; readonly flowpath: string; readonly label: string; readonly section: number }
  | { readonly kind: 'keyword'; readonly component: string; readonly keyword: string; readonly key: string };
export type StopPointerView = { readonly key: string; readonly params: Record<string, string> };
export type StopReasonView = {
  readonly known: boolean;
  readonly titleKey: string;
  readonly detailKey: string;
  readonly params: Record<string, string>;
  readonly stepKeys: readonly string[];
  readonly lastLines: readonly string[];
  readonly evidence: string | null;
  readonly pointer: StopPointerView | null;
};
export function stopPointerView(pointer: StopPointer | null | undefined): StopPointerView | null;
export function stopReasonView(reason: StopReason | null | undefined): StopReasonView | null;
export function stopReasonPrompt(reason: StopReason | null | undefined, caseName: string | null | undefined): string;
