import { useCallback, useRef, useState, useSyncExternalStore } from 'react';
import type { Update } from '@tauri-apps/plugin-updater';
import { currentLocale, translate, useLocale, type I18nKey } from './i18n/index.ts';
import { installUpdate } from './updateInstall';
import {
  browserStorage,
  clearFoundUpdate,
  peekFoundUpdate,
  readCheckOnLaunch,
  subscribeFoundUpdate,
  writeCheckOnLaunch,
} from './updateAutoCheck.mjs';

/**
 * Update surface for the packaged desktop build.
 *
 * Checking, downloading and installing are three separate operator decisions,
 * not one button. This app supervises OLGA runs: pulling ~70 MB over a site
 * connection and swapping the binary underneath a study both deserve their own
 * yes. The signature is verified against the public key compiled into the app
 * before anything is written to disk, so a release the key does not vouch for
 * fails closed here.
 *
 * Outside the Tauri shell (plain `npm run dev` in a browser) the plugin APIs do
 * not exist. The panel says so instead of throwing.
 *
 * Deliberately free of useEffect: nothing here may start on mount.
 */

type Phase =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'current' }
  | { kind: 'available'; version: string; notes: string | null }
  | { kind: 'downloading'; version: string; received: number; total: number | null; startedAt: number }
  | { kind: 'downloaded'; version: string; bytes: number }
  | { kind: 'installing'; version: string }
  | { kind: 'blocked'; version: string; message: string }
  | { kind: 'unsupported' }
  | { kind: 'error'; message: string; key: I18nKey | null; backendStopped: boolean };

const MB = 1_000_000;

function describeError(error: unknown): string | null {
  if (error instanceof Error) return error.message;
  return typeof error === 'string' ? error : null;
}

function failedPhase(message: string | null, key: I18nKey | null, backendStopped = false) {
  return { kind: 'error', message: message ?? '', key, backendStopped } as const;
}

function mb(bytes: number): string {
  return (bytes / MB).toFixed(1);
}

function rate(received: number, startedAt: number, t: (key: 'update.rate', vars: Record<string, string | number>) => string): string | null {
  const seconds = (performance.now() - startedAt) / 1000;
  if (seconds < 0.75 || received <= 0) return null;
  const value = mb(received / seconds);
  return t('update.rate', { value }) ?? `${value} MB/s`;
}

export default function UpdatePanel({ currentVersion }: { currentVersion: string }) {
  // The Update handle has to survive between the check, the download and the
  // install; re-checking in between would discard the downloaded package.
  const pending = useRef<Update | null>(null);
  // A version found by the launch check arrives here as a handle, so the user can download it
  // without a second check. It is read, not consumed, so a repeated render sees it too, and a
  // panel that is already open shows it when the check finishes. It only replaces the idle state,
  // never a check, download or install the user started.
  const found = useSyncExternalStore(subscribeFoundUpdate, peekFoundUpdate);
  const [state, setPhase] = useState<Phase>({ kind: 'idle' });
  const phase: Phase =
    found && state.kind === 'idle' ? { kind: 'available', version: found.version, notes: found.body ?? null } : state;
  const [checkOnLaunch, setCheckOnLaunch] = useState(() => readCheckOnLaunch(browserStorage()));
  const { t } = useLocale();
  // The Install button unmounts while installing, so after a refusal or failure focus has to be
  // handed back explicitly or a keyboard user lands on the page body.
  const installButton = useRef<HTMLButtonElement | null>(null);
  const checkButton = useRef<HTMLButtonElement | null>(null);

  const check = useCallback(async () => {
    setPhase({ kind: 'checking' });
    try {
      const { check: checkForUpdate } = await import('@tauri-apps/plugin-updater');
      clearFoundUpdate();
      await pending.current?.close();
      pending.current = null;

      const update = await checkForUpdate();
      if (!update) {
        setPhase({ kind: 'current' });
        return;
      }
      pending.current = update;
      setPhase({ kind: 'available', version: update.version, notes: update.body ?? null });
    } catch (error) {
      const message = describeError(error);
      setPhase(
        message && /not (?:a )?(?:function|found)|undefined|__TAURI/i.test(message)
          ? { kind: 'unsupported' }
          : failedPhase(message, message ? null : 'update.checkFailed'),
      );
    }
  }, []);

  const download = useCallback(async (version: string) => {
    const update = pending.current ?? peekFoundUpdate();
    pending.current = update;
    if (!update) {
      setPhase(failedPhase(null, 'update.downloadStale'));
      return;
    }
    const startedAt = performance.now();
    setPhase({ kind: 'downloading', version, received: 0, total: null, startedAt });
    try {
      let received = 0;
      let total: number | null = null;
      await update.download((event) => {
        if (event.event === 'Started') {
          total = event.data.contentLength ?? null;
        } else if (event.event === 'Progress') {
          received += event.data.chunkLength;
          setPhase({ kind: 'downloading', version, received, total, startedAt });
        }
      });
      setPhase({ kind: 'downloaded', version, bytes: received });
    } catch (error) {
      const message = describeError(error);
      setPhase(failedPhase(message, message ? null : 'update.checkFailed'));
    }
  }, []);

  const installAndRestart = useCallback(async (version: string) => {
    const update = pending.current;
    if (!update) {
      setPhase(failedPhase(null, 'update.installStale'));
      return;
    }
    setPhase({ kind: 'installing', version });
    let relaunch: () => Promise<void>;
    let invoke: (command: string) => Promise<unknown>;
    try {
      ({ relaunch } = await import('@tauri-apps/plugin-process'));
      ({ invoke } = await import('@tauri-apps/api/core'));
    } catch (error) {
      const message = describeError(error);
      setPhase(failedPhase(message, message ? null : 'update.checkFailed'));
      return;
    }
    // The native command asks the backend whether any run is starting, running or of unknown
    // status, and refuses to stop it unless the answer is a confirmed no. The installer
    // replaces the sidecar's executable, and the Windows updater exits without a normal
    // shutdown, so the backend has to be stopped here, but only once that is safe.
    const outcome = await installUpdate({
      stop: () => invoke('stop_sidecar'),
      install: () => update.install(),
      relaunch,
      describe: (error: unknown) => describeError(error) ?? translate(currentLocale(), 'update.checkFailed'),
    });
    if (outcome.kind === 'blocked') {
      setPhase({ kind: 'blocked', version, message: outcome.message });
      requestAnimationFrame(() => installButton.current?.focus());
    } else if (outcome.kind === 'failed') {
      requestAnimationFrame(() => checkButton.current?.focus());
      setPhase({ kind: 'error', message: outcome.message, key: null, backendStopped: outcome.backendStopped });
    }
  }, []);

  const busy = phase.kind === 'checking' || phase.kind === 'downloading' || phase.kind === 'installing';
  const percent =
    phase.kind === 'downloading' && phase.total
      ? Math.min(100, (phase.received / phase.total) * 100)
      : null;

  const errorText = phase.kind === 'error'
    ? `${phase.key ? t(phase.key) : phase.message}${phase.backendStopped ? ` ${t('update.backendStopped')}` : ''}`
    : '';

  return (
    <article className="settings-card update-card">
      <h3 className="settings-h">{t('update.title')}</h3>
      <p className="settings-note">{t('update.note')}</p>

      <div className="settings-current-row">
        <span>{t('update.installed')}</span>
        <p className="settings-current">v{currentVersion}</p>
      </div>

      <div className="update-actions">
        <button ref={checkButton} type="button" onClick={check} disabled={busy}>
          {phase.kind === 'checking' ? t('update.checking') : t('update.check')}
        </button>

        {phase.kind === 'available' && (
          <button type="button" className="update-go" onClick={() => download(phase.version)}>
            {t('update.downloadVersion', { version: phase.version })}
          </button>
        )}

        {(phase.kind === 'downloaded' || phase.kind === 'blocked') && (
          <button ref={installButton} type="button" className="update-go" onClick={() => installAndRestart(phase.version)}>
            {t('update.installRestart')}
          </button>
        )}
      </div>

      {(phase.kind === 'downloading' || phase.kind === 'downloaded' || phase.kind === 'installing') && (
        <div
          className={`update-progress${phase.kind === 'downloading' && percent === null ? ' is-indeterminate' : ''}${
            phase.kind === 'downloading' ? ' is-active' : ' is-complete'
          }`}
          role="progressbar"
          aria-label={t('update.progressAria', { version: phase.version })}
          aria-valuemin={0}
          aria-valuemax={100}
          {...(percent === null ? {} : { 'aria-valuenow': Math.round(percent) })}
        >
          <div className="update-progress-track">
            <div
              className="update-progress-fill"
              style={{ width: phase.kind === 'downloading' ? `${percent ?? 100}%` : '100%' }}
            >
              <span className="update-progress-sheen" aria-hidden="true" />
            </div>
          </div>
          <div className="update-progress-meta">
            <span className="update-progress-figure">
              {phase.kind === 'downloading'
                ? percent === null
                  ? t('update.downloadedAmount', { value: mb(phase.received) }) ?? `${mb(phase.received)} MB`
                  : `${Math.round(percent)}%`
                : phase.kind === 'downloaded'
                  ? t('update.readyToInstall')
                  : t('update.installing')}
            </span>
            <span className="update-progress-detail">
              {phase.kind === 'downloading'
                ? [
                    phase.total ? t('update.progressDetail', { received: mb(phase.received), total: mb(phase.total) }) ?? `${mb(phase.received)} / ${mb(phase.total)} MB` : null,
                    rate(phase.received, phase.startedAt, t),
                  ]
                    .filter(Boolean)
                    .join(' · ')
                : phase.kind === 'downloaded'
                  ? t('update.downloadedVerified', { size: mb(phase.bytes) })
                  : t('update.restarting')}
            </span>
          </div>
        </div>
      )}

      <p className="update-status" role="status" aria-live="polite">
        {phase.kind === 'idle' && t('update.idle')}
        {phase.kind === 'checking' && t('update.connecting')}
        {phase.kind === 'current' && t('update.current')}
        {phase.kind === 'available' && t('update.available', { version: phase.version })}
        {phase.kind === 'downloading' && t('update.downloading', { version: phase.version })}
        {phase.kind === 'downloaded' && t('update.downloaded', { version: phase.version })}
        {phase.kind === 'installing' && t('update.installingStatus', { version: phase.version })}
        {phase.kind === 'unsupported' && t('update.unsupported')}
        {phase.kind === 'blocked' && phase.message}
        {phase.kind === 'error' && errorText}
      </p>

      {phase.kind === 'available' && phase.notes && (
        <pre className="update-notes">{phase.notes}</pre>
      )}

      <label className="update-launch-toggle">
        <input
          type="checkbox"
          checked={checkOnLaunch}
          onChange={(event) => {
            setCheckOnLaunch(event.target.checked);
            writeCheckOnLaunch(browserStorage(), event.target.checked);
          }}
        />
        <span>{t('update.checkOnLaunch')}</span>
      </label>
    </article>
  );
}
