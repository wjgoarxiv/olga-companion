/* ProxyPanel: user-facing toggle for the corporate-proxy seam.
 *
 * Mirrors the enterprise-proxy guide's shape: host/port/probe-target fields,
 * a Test-now button, and a verdict line. The toggle can go to "on" only after
 * a successful probe; the save button reflects that gate so the user sees
 * why it is disabled. Errors are not hidden — the user has to know whether
 * the port is refused, the proxy returned 502, or the probe timed out.
 */

import { useEffect, useState, type ReactElement } from 'react';
import { apiFetch } from './sessionTransport';
import { jsonOrThrow } from './sessionResponse';
import { useLocale, type I18nKey } from './i18n/index.ts';
import { refresh as refreshProxyStatus } from './proxyStatus.mjs';

type ProbeKind =
  | 'tcp_refused'
  | 'tcp_timeout'
  | 'connect_timeout'
  | 'response_timeout'
  | 'http_status'
  | 'empty_response'
  | 'malformed'
  | 'io';

type ProbeVerdict = {
  ok: boolean;
  status_code: number | null;
  error_kind: ProbeKind | null;
  error: string | null;
  elapsed_ms: number;
} | null;

type ProxyPrefs = {
  enabled: boolean;
  host: string;
  port: number;
  probe_target: string;
  probe_port: number;
  last_probe: ProbeVerdict;
};

const DEFAULTS: ProxyPrefs = {
  enabled: false,
  host: '127.0.0.1',
  port: 8888,
  probe_target: 'api.openai.com',
  probe_port: 443,
  last_probe: null,
};

export default function ProxyPanel(): ReactElement {
  const { t } = useLocale();
  const [prefs, setPrefs] = useState<ProxyPrefs>(DEFAULTS);
  const [working, setWorking] = useState(false);
  const [testFeedback, setTestFeedback] = useState<ProbeVerdict>(null);
  const [savedOnce, setSavedOnce] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = (await jsonOrThrow(await apiFetch('/api/proxy'))) as ProxyPrefs;
        if (!cancelled) {
          setPrefs(body);
          setTestFeedback(body.last_probe);
        }
      } catch {
        // offline or expired; handled by the global transport-failure banner
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const probeOk = testFeedback?.ok === true;
  const saveBlocked = prefs.enabled && !probeOk;

  async function runTest(): Promise<void> {
    setWorking(true);
    try {
      const body = (await jsonOrThrow(
        await apiFetch('/api/proxy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...prefs, enabled: true }),
        }),
      )) as ProxyPrefs;
      setTestFeedback(body.last_probe);
      setPrefs((p) => ({ ...p, last_probe: body.last_probe }));
    } catch {
      setTestFeedback({ ok: false, status_code: null, error_kind: 'io', error: 'offline', elapsed_ms: 0 });
    } finally {
      setWorking(false);
    }
  }

  async function save(): Promise<void> {
    setWorking(true);
    try {
      const body = (await jsonOrThrow(
        await apiFetch('/api/proxy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(prefs),
        }),
      )) as ProxyPrefs;
      setPrefs(body);
      setTestFeedback(body.last_probe);
      setSavedOnce(true);
      void refreshProxyStatus();
    } catch {
      setTestFeedback({ ok: false, status_code: null, error_kind: 'io', error: 'offline', elapsed_ms: 0 });
    } finally {
      setWorking(false);
    }
  }

  return (
    <article className="settings-card proxy-card">
      <h3 className="settings-h">{t('settings.proxyTitle')}</h3>
      <p className="settings-note">{t('settings.proxyIntro')}</p>
      <div className="proxy-field">
        <label>
          <input
            type="checkbox"
            checked={prefs.enabled}
            onChange={(e) => setPrefs((p) => ({ ...p, enabled: e.target.checked }))}
          />
          {t('settings.proxyEnabled')}
        </label>
      </div>
      <div className="proxy-field">
        <label>{t('settings.proxyHost')}
          <input value={prefs.host} onChange={(e) => setPrefs((p) => ({ ...p, host: e.target.value }))} />
        </label>
        <label>{t('settings.proxyPort')}
          <input
            type="number" min={1} max={65535}
            value={prefs.port}
            onChange={(e) => setPrefs((p) => ({ ...p, port: Number(e.target.value) || 0 }))}
          />
        </label>
      </div>
      <div className="proxy-field">
        <label>{t('settings.proxyProbeTarget')}
          <input
            value={prefs.probe_target}
            onChange={(e) => setPrefs((p) => ({ ...p, probe_target: e.target.value }))}
          />
        </label>
      </div>
      <div className="proxy-actions">
        <button type="button" className="ui-button" onClick={() => void runTest()} disabled={working}>
          {t('settings.proxyTestNow')}
        </button>
        <button type="button" className="ui-button" onClick={() => void save()} disabled={working || saveBlocked}>
          {t('settings.proxySave')}
        </button>
      </div>
      <p className="proxy-verdict" aria-live="polite">{renderVerdict(t, testFeedback, savedOnce)}</p>
    </article>
  );
}

function renderVerdict(t: (k: I18nKey, p?: Record<string, string>) => string, verdict: ProbeVerdict, _savedOnce: boolean): string {
  if (verdict === null) return '';
  if (verdict.ok) return t('settings.proxyOk', { ms: String(verdict.elapsed_ms) });
  switch (verdict.error_kind) {
    case 'tcp_refused':
      return t('settings.proxyRefused');
    case 'tcp_timeout':
    case 'connect_timeout':
    case 'response_timeout':
      return t('settings.proxyTimeout');
    case 'http_status':
      return t('settings.proxyHttpStatus', { code: String(verdict.status_code ?? '?') });
    default:
      return t('settings.proxyGenericError', { kind: String(verdict.error_kind ?? 'unknown') });
  }
}
