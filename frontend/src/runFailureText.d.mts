export type RunFailureView = {
  readonly titleKey: string;
  readonly detailKey: string;
  readonly stepKeys: readonly string[];
  readonly params: Record<string, string>;
  readonly serverReason: string | null;
};
export function runFailureView(
  failure: { readonly code: string; readonly detail?: string; readonly variant?: string } | null | undefined,
  exitCode: number | null | undefined,
): RunFailureView | null;
