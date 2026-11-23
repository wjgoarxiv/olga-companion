type Translate = (key: string, vars?: Record<string, string | number>) => string;
type Identified = { readonly approved_change?: { readonly changes: readonly { readonly path: string; readonly before: unknown; readonly after: unknown; readonly unit?: string }[] } | null };
export function changeLabel(file: Identified | null | undefined, t: Translate): string | null;
export function runColor(id: string): string;
