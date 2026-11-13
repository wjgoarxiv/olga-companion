import { useCallback, useRef, useState, useSyncExternalStore } from 'react';
import type { Update } from '@tauri-apps/plugin-updater';
import { currentLocale, translate, useLocale, type I18nKey } from './i18n/index.ts';
import { RollingNumber } from './ui/RollingNumber';
import { UPDATE_STAGES, keepsUpdateHandle, stageOfPhase, type UpdateStageId } from './updateStages.mjs';
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
  | { kind: 'error'; message: string; key: I18nKey | null; backendStopped: boolean; stage: 'checking' | 'downloading' | 'installing' };

const MB = 1_000_000;

function describeError(error: unknown): string | null {
  if (error instanceof Error) return error.message;
  return typeof error === 'string' ? error : null;
}

function failedPhase(
  message: string | null,
  key: I18nKey | null,
  backendStopped = false,
  stage: 'checking' | 'downloading' | 'installing' = 'checking',
) {
  return { kind: 'error', message: message ?? '', key, backendStopped, stage } as const;
}

function mb(bytes: number): string {
  return (bytes / MB).toFixed(1);
}

const RING_C = 2 * Math.PI * 16;

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

  const keepHandle = keepsUpdateHandle(phase);

  const check = useCallback(async () => {
    // Once the package is downloaded (or Install was refused) the handle is the only copy of it.
    // A fresh check would clear and close it and force a second download, so Check stays enabled
    // but hands focus to the next real step instead of starting over.
    if (keepHandle) {
      installButton.current?.focus();
      return;
    }
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
  }, [keepHandle]);

  const download =useCallback(async (version: string) => {
    const update = pending.current ?? peekFoundUpdate();
    pending.current = update;
    if (!update) {
      setPhase(failedPhase(null, 'update.downloadStale', false, 'downloading'));
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
      setPhase(failedPhase(message, message ? null : 'update.checkFailed', false, 'downloading'));
    }
  }, []);

  const installAndRestart = useCallback(async (version: string) => {
    const update = pending.current;
    if (!update) {
      setPhase(failedPhase(null, 'update.installStale', false, 'installing'));
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
      setPhase(failedPhase(message, message ? null : 'update.checkFailed', false, 'installing'));
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
      setPhase({ kind: 'error', message: outcome.message, key: null, backendStopped: outcome.backendStopped, stage: 'installing' });
    }
  }, []);

  const busy = phase.kind === 'checking' || phase.kind === 'downloading' || phase.kind === 'installing';
  const percent =
    phase.kind === 'downloading' && phase.total
      ? Math.min(100, (phase.received / phase.total) * 100)
      : null;
  // The notes toggle resets per version via the key below, so no effect is needed.
  const [notesOpen, setNotesOpen] = useState(false);
  const track = stageOfPhase(phase);
  const stageLabels: Record<UpdateStageId, string> = {
    checking: t('update.stage.checking'),
    available: t('update.stage.available'),
    downloading: t('update.stage.downloading'),
    verifying: t('update.stage.verifying'),
    installing: t('update.stage.installing'),
    restarting: t('update.stage.restarting'),
  };
  const elapsedSeconds = phase.kind === 'downloading' ? (performance.now() - phase.startedAt) / 1000 : 0;
  const mbps = phase.kind === 'downloading' && elapsedSeconds >= 0.75 && phase.received > 0
    ? phase.received / MB / elapsedSeconds
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

      <ol className="update-stages" aria-label={t('update.stagesAria')}>
        {UPDATE_STAGES.map((id) => (
          <li
            key={id}
            data-stage={id}
            className={`update-stage is-${track.states[id]}`}
            aria-current={track.active === id ? 'step' : undefined}
          >
            <span className="update-stage-dot" aria-hidden="true" />
            <span className="update-stage-label">{stageLabels[id]}</span>
          </li>
        ))}
      </ol>

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
          <div className="update-progress-row">
            <svg className="update-ring" viewBox="0 0 40 40" aria-hidden="true" focusable="false">
              <circle className="update-ring-track" cx="20" cy="20" r="16" />
              <circle
                className="update-ring-fill"
                cx="20"
                cy="20"
                r="16"
                strokeDasharray={RING_C}
                strokeDashoffset={RING_C * (1 - (percent ?? 100) / 100)}
              />
            </svg>
            <div className="update-progress-track">
              <div
                className="update-progress-fill"
                style={{ width: phase.kind === 'downloading' ? `${percent ?? 100}%` : '100%' }}
              >
                <span className="update-progress-sheen" aria-hidden="true" />
              </div>
            </div>
          </div>
          <div className="update-progress-meta">
            <span className="update-progress-figure">
              {phase.kind === 'downloading'
                ? percent === null
                  ? <RollingNumber value={phase.received} format={(n) => `${(n / MB).toFixed(1)} MB`} />
                  : <RollingNumber value={percent} format={(n) => `${Math.round(n)}%`} />
                : phase.kind === 'downloaded'
                  ? t('update.readyToInstall')
                  : t('update.installing')}
            </span>
            <span className="update-progress-detail">
              {phase.kind === 'downloading'
                ? (
                  <>
                    {phase.total
                      ? (
                        <span>
                          {t('update.progressDetail', { received: mb(phase.received), total: mb(phase.total) })
                            ?? `${mb(phase.received)} / ${mb(phase.total)} MB`}
                        </span>
                      )
                      : null}
                    {mbps !== null
                      ? (
                        <>
                          <span aria-hidden="true">·</span>
                          <RollingNumber value={mbps} format={(n) => `${n.toFixed(1)} MB/s`} />
                        </>
                      )
                      : null}
                  </>
                )
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

      {phase.kind === 'available' && (
        <p className="update-version-line">
          <span key={phase.version} className="update-version-reveal">v{phase.version}</span>
        </p>
      )}

      {phase.kind === 'available' && phase.notes && (
        <div className="update-notes-wrap" key={phase.version}>
          <button
            type="button"
            className="update-notes-toggle"
            aria-expanded={notesOpen}
            onClick={() => setNotesOpen((open) => !open)}
          >
            {notesOpen ? t('update.hideNotes') : t('update.showNotes')}
          </button>
          {notesOpen && <pre className="update-notes update-notes-open">{phase.notes}</pre>}
        </div>
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
