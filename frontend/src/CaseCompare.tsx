import { useEffect, useState } from 'react';
import { fetchCaseDiff, type CaseDiff, type CaseDiffRow } from './caseEditApi';
import { useLocale } from './i18n/index.ts';

// A record without a LABEL keeps its order number (#1, #2) so two of them read apart.
const place = (row: CaseDiffRow): string => {
  const record = `${row.keyword} ${row.label}`;
  return row.component ? `${row.component} · ${record}` : record;
};
const baseName = (rel: string): string => rel.split('/').pop() ?? rel;

/* The differences between two cases, key by key. */
export function CaseDiffResult({ diff }: { readonly diff: CaseDiff }) {
  const { t } = useLocale();
  // The file names, or the workspace paths when both files have the same name.
  const sameName = baseName(diff.a) === baseName(diff.b);
  const name = (rel: string): string => (sameName ? rel : baseName(rel));
  if (diff.same) return <p className="case-compare-same" role="status">{t('compare.same')}</p>;
  return (
    <div className="case-compare-result">
      {diff.changed.length > 0 && (
        <table className="case-compare-table">
          <caption>{t('compare.changed', { count: diff.changed.length })}</caption>
          <thead><tr><th scope="col">{t('compare.where')}</th><th scope="col">{t('compare.key')}</th><th scope="col">{name(diff.a)}</th><th scope="col">{name(diff.b)}</th></tr></thead>
          <tbody>
            {diff.changed.map((row) => (
              <tr key={`${row.component ?? ''}\u0000${row.keyword}\u0000${row.label}\u0000${row.key}`}>
                <td>{place(row)}</td>
                <td><code>{row.key}</code></td>
                <td>{row.before ?? <em>{t('compare.absent')}</em>}</td>
                <td>{row.after ?? <em>{t('compare.absent')}</em>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {diff.removed.length > 0 && (
        <p><strong>{t('compare.onlyIn', { name: name(diff.a), count: diff.removed.length })}</strong> {diff.removed.map(place).join(', ')}</p>
      )}
      {diff.added.length > 0 && (
        <p><strong>{t('compare.onlyIn', { name: name(diff.b), count: diff.added.length })}</strong> {diff.added.map(place).join(', ')}</p>
      )}
      {diff.truncated && <p className="case-compare-note">{t('compare.truncated')}</p>}
    </div>
  );
}

/* Pick another workspace case and see what differs; read-only. */
export function CaseCompare({ rel, others }: { readonly rel: string; readonly others: readonly string[] }) {
  const { t } = useLocale();
  const [other, setOther] = useState('');
  const [diff, setDiff] = useState<CaseDiff | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    setDiff(null);
    setProblem(null);
    if (!other) return;
    let live = true;
    fetchCaseDiff(rel, other)
      .then((next) => { if (live) setDiff(next); })
      .catch((cause: unknown) => { if (live) setProblem(cause instanceof Error ? cause.message : String(cause)); });
    return () => { live = false; };
  }, [rel, other]);
  if (others.length === 0) return null;
  return (
    <details className="case-compare">
      <summary>{t('compare.title')}</summary>
      <label className="case-compare-pick">
        <span>{t('compare.with')}</span>
        <select value={other} onChange={(event) => setOther(event.target.value)}>
          <option value="">{t('compare.pick')}</option>
          {others.map((candidate) => <option key={candidate} value={candidate}>{candidate}</option>)}
        </select>
      </label>
      {problem && <p className="case-compare-note" role="alert">{problem}</p>}
      {diff && <CaseDiffResult diff={diff} />}
    </details>
  );
}
