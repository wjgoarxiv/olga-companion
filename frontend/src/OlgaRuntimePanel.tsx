/* OlgaRuntimePanel: which OLGA install the runner will use, and why.
 *
 * The panel shows GET /api/run/detect as-is: every detected install with
 * its version and kind, the selected executable, and the server's selection
 * rationale. "Pick executable" opens a native .exe dialog and persists the
 * choice with the same priority as OLGA_EXE_PATH; "Use automatic" clears it.
 */

import { useEffect, useState, type ReactElement } from 'react';
import { apiFetch } from './sessionTransport';
import { jsonOrThrow } from './sessionResponse';
import { useLocale } from './i18n/index.ts';
import { createNativeDialogRequestId } from './nativeDialogRequest';
import { Button } from './ui/Button';

type RuntimeCandidate = {
  readonly exe: string;
  readonly kind: string;
  readonly version: string | null;
  readonly source: string;
  readonly runtime_id?: string;
};

type RuntimeDetection = {
  readonly detected: boolean;
  readonly exe: string | null;
  readonly kind: string | null;
  readonly version: string | null;
  readonly source: string | null;
  readonly selection_status: string;
  readonly rationale: string;
  readonly candidates: RuntimeCandidate[];
};

type PickResult =
  | { readonly status: 'selected'; readonly path: string; readonly detection: RuntimeDetection }
  | { readonly status: 'cancelled' }
  | { readonly status: 'unavailable'; readonly reason: string };

export default function OlgaRuntimePanel(): ReactElement {
  const { t } = useLocale();
  const [detection, setDetection] = useState<RuntimeDetection | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh(): Promise<void> {
    setError(null);
    try {
      const body = (await jsonOrThrow(await apiFetch('/api/run/detect'))) as RuntimeDetection;
      setDetection(body);
    } catch {
      setError('offline');
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = (await jsonOrThrow(await apiFetch('/api/run/detect'))) as RuntimeDetection;
        if (!cancelled) setDetection(body);
      } catch {
        if (!cancelled) setError('offline');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function pickExecutable(): Promise<void> {
    setWorking(true);
    setError(null);
    try {
      const body = (await jsonOrThrow(
        await apiFetch('/api/run/olga-exe/pick', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_id: createNativeDialogRequestId() }),
        }),
      )) as PickResult;
      if (body.status === 'selected') setDetection(body.detection);
      else if (body.status === 'unavailable') setError(body.reason);
    } catch {
      setError('pick_failed');
    } finally {
      setWorking(false);
    }
  }

  async function clearOverride(): Promise<void> {
    setWorking(true);
    setError(null);
    try {
      const body = (await jsonOrThrow(
        await apiFetch('/api/run/olga-exe/override', { method: 'DELETE' }),
      )) as { readonly cleared: boolean; readonly detection: RuntimeDetection };
      setDetection(body.detection);
    } catch {
      setError('clear_failed');
    } finally {
      setWorking(false);
    }
  }

  const manual = detection?.source === 'manual:settings';

  return (
    <article className="settings-card runtime-card" aria-label={t('runtime.title')}>
      <h3 className="settings-h">{t('runtime.title')}</h3>
      <p className="settings-note">{t('runtime.note')}</p>
      {detection && (
        <>
          <dl className="runtime-summary">
            <dt>{t('runtime.selected')}</dt>
            <dd className="evidence-value-technical">
              {detection.detected && detection.version
                ? <>{t('runtime.versionLabel', { version: detection.version })}{' · '}{detection.kind ?? ''}</>
                : t('runtime.none')}
            </dd>
            <dt>{t('runtime.reason')}</dt>
            <dd>{detection.rationale}</dd>
          </dl>
          {detection.candidates.length > 0 && (
            <ul className="runtime-candidates">
              {detection.candidates.map((candidate) => (
                <li key={`${candidate.source}:${candidate.exe}`}>
                  {candidate.version
                    ? t('runtime.versionLabel', { version: candidate.version })
                    : t('runtime.unknownVersion')}
                  {' · '}{candidate.kind}
                  {candidate.exe === detection.exe ? ` — ${t('runtime.selectedMark')}` : ''}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className="runtime-actions">
        <Button variant="secondary" onClick={() => { void pickExecutable(); }} disabled={working}>
          {t('runtime.pickExe')}
        </Button>
        {manual && (
          <Button variant="secondary" onClick={() => { void clearOverride(); }} disabled={working}>
            {t('runtime.clearOverride')}
          </Button>
        )}
        <Button variant="secondary" onClick={() => { void refresh(); }} disabled={working}>
          {t('runtime.refresh')}
        </Button>
      </div>
      {error && (
        <p className="runtime-error" aria-live="polite">
          {error === 'offline'
            ? t('runtime.offline')
            : error === 'pick_failed'
              ? t('runtime.pickFailed')
              : error === 'clear_failed'
                ? t('runtime.clearFailed')
                : error}
        </p>
      )}
    </article>
  );
}
