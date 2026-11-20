export type GlossaryEntry = {
  readonly term: string;
  readonly kind: string;
  readonly meaning: string;
  readonly meaning_en?: string;
  readonly meaning_ko?: string;
  readonly unit?: string;
  readonly source: { readonly file: string; readonly line: number };
};

/** The meaning in the UI language; the OLGA keyword itself stays in English. */
export function entryMeaning(entry: GlossaryEntry, locale: string): string {
  return (locale === 'ko' ? entry.meaning_ko : entry.meaning_en) ?? entry.meaning;
}

/** Exact term match, case-insensitive. Unknown terms resolve to null, never invented text. */
export function findEntry(entries: readonly GlossaryEntry[], term: string): GlossaryEntry | null {
  const key = term.trim().toUpperCase();
  if (!key) return null;
  return entries.find((entry) => entry.term.toUpperCase() === key) ?? null;
}
