type Translate = (key: string, vars?: Record<string, string | number>) => string;
type Change = { readonly path: string; readonly before: unknown; readonly after: unknown; readonly unit?: string };
type RunFile = {
  readonly name: string;
  readonly source_name?: string | null;
  readonly modified_ns: number;
  readonly approved_change?: { readonly changes: readonly Change[] } | null;
};
export function runLabel(file: RunFile, locale: string, t?: Translate): string;
export function chipSource(
  series: { readonly source?: string | null; readonly fileId?: string | null },
  runs: readonly (RunFile & { readonly id: string })[],
  locale: string,
  t?: Translate,
): string | undefined;
