import { useEffect, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { apiFetch } from './sessionTransport';

export interface OlgaInstallRow {
  readonly version: string | null;
  readonly kind: string;
  readonly source: string | null;
  readonly file: string;
  readonly runnable: boolean;
  readonly selected: boolean;
}

export interface SupportBundle {
  readonly schema: number;
  readonly app_version: string;
  readonly olga: readonly OlgaInstallRow[];
  readonly [key: string]: unknown;
}

/** The OLGA installs found: version, program file, and whether the app can start it. */
export function VersionMatrix({ rows }: { readonly rows: readonly OlgaInstallRow[] }) {
  const { t } = useLocale();
  if (rows.length === 0) return <p className="env-support-empty">{t('env.versions.none')}</p>;
  return (
    <table className="env-versions">
      <caption>{t('env.versions.title')}</caption>
      <thead>
        <tr>
          <th scope="col">{t('env.versions.version')}</th>
          <th scope="col">{t('env.versions.file')}</th>
          <th scope="col">{t('env.versions.runs')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          // Only the file name is sent, so two installs can look alike; the place in the list tells them apart.
          <tr key={`${index}-${row.file}-${row.version ?? ''}-${row.kind}`} aria-current={row.selected ? 'true' : undefined}>
            <td>{row.version ?? t('env.versions.unknown')}{row.selected ? ` · ${t('env.versions.selected')}` : ''}</td>
            <td><code>{row.file}</code></td>
            <td>{row.runnable ? t('env.versions.yes') : t('env.versions.no')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The support info as text the user selects and copies with Ctrl+C. The app never touches the
    clipboard itself: in WebView2 that opens a clipboard permission prompt. */
export function SupportText({ bundle }: { readonly bundle: SupportBundle }) {
  const { t } = useLocale();
  return (
    <details className="env-support-text">
      <summary>{t('env.support.show')}</summary>
      <textarea
        readOnly
        rows={8}
        aria-label={t('env.support.title')}
        value={JSON.stringify(bundle, null, 2)}
        onFocus={(event) => event.currentTarget.select()}
      />
      <small className="env-support-hint">{t('env.support.copyHint')}</small>
    </details>
  );
}

/** Versions and status codes, read once when the panel opens. */
export default function SupportInfo() {
  const { t } = useLocale();
  const [bundle, setBundle] = useState<SupportBundle | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/api/support-bundle')
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: SupportBundle | null) => { if (!cancelled) setBundle(payload); })
      .catch(() => { if (!cancelled) setBundle(null); });
    return () => { cancelled = true; };
  }, []);

  return (
    <section className="env-support" aria-label={t('env.support.title')}>
      {bundle && <VersionMatrix rows={bundle.olga} />}
      {bundle && <SupportText bundle={bundle} />}
      <small className="env-support-note">{t('env.support.note')}</small>
    </section>
  );
}
