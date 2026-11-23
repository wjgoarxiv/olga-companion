import { en } from './i18n/en.ts';
import type { I18nKey } from './i18n/index.ts';

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

// The glossary data gives some units as English words ("length", "heat capacity unit"). Each such
// word is the English text of a `glossary.unit.*` key, so it gets a label in the UI language.
// Anything else is a unit symbol or OLGA code, shown through formatUnit.
const UNIT_WORD_KEYS: ReadonlyMap<string, I18nKey> = new Map(
  (Object.keys(en) as I18nKey[])
    .filter((key) => key.startsWith('glossary.unit.'))
    .map((key) => [en[key].toLowerCase(), key]),
);

export function glossaryUnitKey(unit: string): I18nKey | null {
  return UNIT_WORD_KEYS.get(unit.trim().toLowerCase()) ?? null;
}

/** Exact term match, case-insensitive. Unknown terms resolve to null, never invented text. */
export function findEntry(entries: readonly GlossaryEntry[], term: string): GlossaryEntry | null {
  const key = term.trim().toUpperCase();
  if (!key) return null;
  return entries.find((entry) => entry.term.toUpperCase() === key) ?? null;
}
