import { useLocale } from './i18n/index.ts';
import type { CaseLintWarning, KeywordCoverage } from './runContracts';

const number = (value: unknown): string => (typeof value === 'number' ? String(Number(value.toPrecision(4))) : String(value ?? ''));

/* Warn-only checks on the exact .genkey the preview is for. They never stop the run. */
export function CaseLintList({ warnings }: { readonly warnings: readonly CaseLintWarning[] }) {
  const { t } = useLocale();
  if (warnings.length === 0) return null;
  return (
    <div className="run-preview-checks" role="note">
      <strong>{t('lint.title')}</strong>
      <ul>
        {warnings.map((warning, index) => (
          <li key={`${warning.rule}-${index}`}>
            {t(`lint.${warning.rule}`, {
              keyword: warning.keyword,
              label: String(warning.values.label ?? ''),
              value: number(warning.values.value),
              limit: number(warning.values.limit),
            })}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* Which keys of this case the app can change, and how; the rest are named, not hidden. */
export function KeywordCoverageMap({ coverage }: { readonly coverage: KeywordCoverage }) {
  const { t } = useLocale();
  const groups = [
    ['table', coverage.table],
    ['sweep', coverage.sweep],
    ['fixed', coverage.fixed],
  ] as const;
  return (
    <details className="case-edit-coverage">
      <summary>{t('coverage.title')}</summary>
      {groups.map(([group, keys]) => (
        <div key={group} className="case-edit-coverage-group" data-group={group}>
          <strong>{t(`coverage.${group}`, { count: keys.length })}</strong>
          {keys.length > 0 && <p>{keys.map((key) => <code key={key}>{key}</code>)}</p>}
        </div>
      ))}
    </details>
  );
}
