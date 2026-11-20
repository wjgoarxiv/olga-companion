export function runLabel(
  file: { readonly name: string; readonly source_name?: string | null; readonly modified_ns: number },
  locale: string,
): string;
export function chipSource(
  series: { readonly source?: string | null; readonly fileId?: string | null },
  runs: readonly { readonly id: string; readonly name: string; readonly source_name?: string | null; readonly modified_ns: number }[],
  locale: string,
): string | undefined;
