/** The table's own names for a case: a title and a name per OLGA label. The OLGA label
    stays the identity everywhere; a name is shown beside it, never instead of a request. */
export interface CaseMeta {
  readonly title?: string;
  readonly display_names?: Readonly<Record<string, string>>;
}

export type CaseNames = Readonly<Record<string, string>>;

/** Keep only well-formed strings; an old case or a bad payload gives null (nothing to show). */
export function readCaseMeta(value: unknown): CaseMeta | null {
  if (typeof value !== 'object' || value === null) return null;
  const record = value as Record<string, unknown>;
  const title = typeof record.title === 'string' && record.title.trim() !== '' ? record.title.trim() : undefined;
  const raw = typeof record.display_names === 'object' && record.display_names !== null
    ? Object.entries(record.display_names as Record<string, unknown>)
    : [];
  const names = Object.fromEntries(
    raw.filter((entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1].trim() !== ''),
  );
  if (title === undefined && Object.keys(names).length === 0) return null;
  return { ...(title !== undefined ? { title } : {}), ...(Object.keys(names).length > 0 ? { display_names: names } : {}) };
}

/** The table's name for one OLGA label, or null when it has none (or it only repeats the label). */
export function nameFor(label: string, names: CaseNames | null | undefined): string | null {
  const name = names?.[label];
  return typeof name === 'string' && name !== '' && name !== label ? name : null;
}

/** "name (LABEL)" when the table named it, else the OLGA label alone. */
export function labelWithName(label: string, names: CaseNames | null | undefined): string {
  const name = nameFor(label, names);
  return name === null ? label : `${name} (${label})`;
}

/** "title (file name)" when the case has a title, else the file name alone. */
export function caseWithTitle(caseName: string, meta: CaseMeta | null | undefined): string {
  const title = meta?.title;
  return title && title !== caseName ? `${title} (${caseName})` : caseName;
}

/** A short "name (LABEL), …" list for a header; the rest is counted, not listed. */
export function namesSummary(meta: CaseMeta | null | undefined, limit = 4): string {
  const entries = Object.entries(meta?.display_names ?? {}).filter(([label]) => nameFor(label, meta?.display_names) !== null);
  const shown = entries.slice(0, limit).map(([label]) => labelWithName(label, meta?.display_names));
  return entries.length > limit ? `${shown.join(', ')} +${entries.length - limit}` : shown.join(', ');
}

/** Text width in "narrow character" units: Hangul and other wide characters take two. */
export function textUnits(text: string): number {
  let units = 0;
  for (const char of text) units += (char.codePointAt(0) ?? 0) > 0x2e7f ? 2 : 1;
  return units;
}

const metaByCase = new Map<string, CaseMeta>();
const listeners = new Set<() => void>();
let version = 0;

/** The meta the last topology load found for a case file name; the status line reads it. */
export function setCaseMeta(caseName: string, meta: CaseMeta | null): void {
  const had = metaByCase.get(caseName);
  if (meta === null ? had === undefined : JSON.stringify(had) === JSON.stringify(meta)) return;
  if (meta === null) metaByCase.delete(caseName);
  else metaByCase.set(caseName, meta);
  version += 1;
  listeners.forEach((listener) => listener());
}

export function getCaseMeta(caseName: string | null | undefined): CaseMeta | null {
  return caseName ? metaByCase.get(caseName) ?? null : null;
}

export function subscribeCaseMeta(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function getCaseMetaVersion(): number {
  return version;
}
