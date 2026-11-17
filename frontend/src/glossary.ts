export type GlossaryEntry = {
  readonly term: string;
  readonly kind: string;
  readonly meaning: string;
  readonly unit?: string;
  readonly source: { readonly file: string; readonly line: number };
};

/** Exact term match, case-insensitive. Unknown terms resolve to null, never invented text. */
export function findEntry(entries: readonly GlossaryEntry[], term: string): GlossaryEntry | null {
  const key = term.trim().toUpperCase();
  if (!key) return null;
  return entries.find((entry) => entry.term.toUpperCase() === key) ?? null;
}
