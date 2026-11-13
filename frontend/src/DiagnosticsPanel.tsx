/* DiagnosticsPanel: pack a bug-report bundle the user can attach to a GitHub issue.
 *
 * The panel shows a preview (versions, proxy summary, log files the bundle
 * will include), a button that writes the zip into a local temp directory,
 * and a second button that opens a pre-filled GitHub new-issue page. The
 * bundle contains no credentials: just versions, the proxy summary already
 * shown on this page, and the rotating sidecar log.
 */

import { useEffect, useState, type ReactElement } from 'react';
import { apiFetch } from './sessionTransport';
import { jsonOrThrow } from './sessionResponse';
import { useLocale } from './i18n/index.ts';

type LogEntry = { name: string; size_bytes: number; mtime: string };
type Versions = { app_version: string; python_version: string; os: string };
type ProxySummary = {
  enabled: boolean;
  host: string;
  port: number;
  probe_target: string;
  probe_port: number;
  last_probe: { ok: boolean; status_code: number | null; error_kind: string | null; elapsed_ms: number } | null;
};
type Preview = { versions: Versions; proxy: ProxySummary; logs: LogEntry[] };
type BundleResult = { bundle_path: string; size_bytes: number; issue_url: string };

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DiagnosticsPanel(): ReactElement {
  const { t } = useLocale();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [working, setWorking] = useState(false);
  const [bundle, setBundle] = useState<BundleResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = (await jsonOrThrow(await apiFetch('/api/diagnostics'))) as Preview;
        if (!cancelled) setPreview(body);
      } catch {
        if (!cancelled) setError('offline');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function makeBundle(): Promise<void> {
    setWorking(true);
    setError(null);
    try {
      const body = (await jsonOrThrow(
        await apiFetch('/api/diagnostics/bundle', { method: 'POST' }),
      )) as BundleResult;
      setBundle(body);
    } catch {
      setError('bundle_failed');
    } finally {
      setWorking(false);
    }
  }

  function openIssue(): void {
    if (!bundle) return;
    window.open(bundle.issue_url, '_blank', 'noopener,noreferrer');
  }

  const totalLogBytes = preview?.logs.reduce((n, e) => n + e.size_bytes, 0) ?? 0;

  return (
    <article className="settings-card diagnostics-card">
      <h3 className="settings-h">{t('settings.diagnosticsTitle')}</h3>
      <p className="settings-note">{t('settings.diagnosticsIntro')}</p>
      {preview && (
        <dl className="diagnostics-preview">
          <dt>{t('settings.diagnosticsAppVersion')}</dt>
          <dd>{preview.versions.app_version}</dd>
          <dt>{t('settings.diagnosticsOs')}</dt>
          <dd>{preview.versions.os}</dd>
          <dt>{t('settings.diagnosticsProxy')}</dt>
          <dd>{preview.proxy.enabled
            ? t('settings.diagnosticsProxyOn', { host: preview.proxy.host, port: String(preview.proxy.port) })
            : t('settings.diagnosticsProxyOff')}</dd>
          <dt>{t('settings.diagnosticsLogs')}</dt>
          <dd>{t('settings.diagnosticsLogsCount', { n: String(preview.logs.length), size: formatBytes(totalLogBytes) })}</dd>
        </dl>
      )}
      <div className="diagnostics-actions">
        <button type="button" className="ui-button" onClick={() => void makeBundle()} disabled={working || !preview}>
          {t('settings.diagnosticsMakeBundle')}
        </button>
        <button type="button" className="ui-button" onClick={openIssue} disabled={!bundle}>
          {t('settings.diagnosticsOpenIssue')}
        </button>
      </div>
      {bundle && (
        <p className="diagnostics-result" aria-live="polite">
          {t('settings.diagnosticsBundleReady', {
            path: bundle.bundle_path,
            size: formatBytes(bundle.size_bytes),
          })}
        </p>
      )}
      {error && (
        <p className="diagnostics-error" aria-live="polite">
          {error === 'offline' ? t('settings.diagnosticsOffline') : t('settings.diagnosticsBundleFailed')}
        </p>
      )}
    </article>
  );
}
