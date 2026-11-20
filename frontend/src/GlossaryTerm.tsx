import { useEffect, useState, type ReactNode } from 'react';
import { useLocale } from './i18n/index.ts';
import { entryMeaning, findEntry, type GlossaryEntry } from './glossary';
import { apiFetch } from './sessionTransport';

let cached: Promise<readonly GlossaryEntry[]> | null = null;

/** The glossary list is fetched once per session and shared by every trigger. */
function loadGlossary(): Promise<readonly GlossaryEntry[]> {
  if (!cached) {
    cached = apiFetch('/api/glossary')
      .then((response) => response.json())
      .then((payload: { entries?: GlossaryEntry[] }) => payload.entries ?? [])
      .catch(() => []);
  }
  return cached;
}

export default function GlossaryTerm({ term, children }: { readonly term: string; readonly children: ReactNode }) {
  const { t, locale } = useLocale();
  const [entry, setEntry] = useState<GlossaryEntry | null | undefined>(undefined);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadGlossary().then((entries) => {
      if (!cancelled) setEntry(findEntry(entries, term));
    });
    return () => { cancelled = true; };
  }, [term]);

  if (entry === undefined) return <>{children}</>;
  if (entry === null) return <>{children}</>;
  const meaning = entryMeaning(entry, locale);

  return (
    <span className="glossary-term" tabIndex={0} role="button" aria-expanded={open}
      aria-label={`${term}: ${meaning}`}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onClick={() => setOpen((value) => !value)}
      onKeyDown={(event) => {
        if (event.key === 'Escape') setOpen(false);
        else if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          setOpen(true);
        }
      }}>
      {children}
      {open && (
        <span className="glossary-pop" role="status">
          <strong>{entry.term}</strong>
          <span>{meaning}{entry.unit ? ` (${entry.unit})` : ''}</span>
          <span className="glossary-source">{t('glossary.sourceLabel') ?? '출처:'} {entry.source.file}:{entry.source.line}</span>
        </span>
      )}
    </span>
  );
}
