import { useEffect, type ReactElement } from 'react';
import { useLocale } from './i18n/index.ts';
import './styles/boot.css';

export type BootStage = 'starting' | 'connecting';
export type BootFailReason = 'offline' | 'timeout' | 'unavailable';
export type BundleStatus = 'idle' | 'working' | 'ready' | 'failed';

const STAGE_ORDER: readonly BootStage[] = ['starting', 'connecting'];

export default function BootOverlay({
  stage,
  failure,
  leaving,
  bundlePath,
  bundleStatus,
  onRetry,
  onBundle,
}: {
  stage: BootStage;
  failure: BootFailReason | null;
  leaving: boolean;
  bundlePath: string | null;
  bundleStatus: BundleStatus;
  onRetry: () => void;
  onBundle: () => void;
}): ReactElement {
  const { t } = useLocale();
  const failed = failure !== null;
  // While the gate is pending the workbench takes no click or keyboard input.
  // The overlay mounts at boot and unmounts once ready lifts away, so that
  // window is exactly the blocked window; the overlay itself is a sibling.
  useEffect(() => {
    const root = document.querySelector('.wb') as (Element & { inert?: boolean }) | null;
    if (!root) return undefined;
    try {
      root.inert = true;
    } catch {
      return undefined;
    }
    return () => {
      try {
        root.inert = false;
      } catch {
        return;
      }
    };
  }, []);
  return (
    <div
      className={leaving ? 'boot-overlay is-leaving' : 'boot-overlay'}
      role={failed ? 'alert' : 'status'}
      aria-label={t('boot.loading')}
    >
      <div className="boot-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      {!failed && (
        <div className="boot-pending">
          <p className="boot-stage">{t(`boot.stage.${stage}`)}</p>
          <div
            className="boot-bar"
            role="progressbar"
            aria-label={t('boot.loading')}
            aria-valuemin={0}
            aria-valuemax={STAGE_ORDER.length}
            aria-valuenow={STAGE_ORDER.indexOf(stage) + 1}
          >
            <span style={{ transform: `scaleX(${(STAGE_ORDER.indexOf(stage) + 1) / STAGE_ORDER.length})` }} />
          </div>
        </div>
      )}
      {failed && (
        <div className="boot-failed">
          <p className="boot-failed-title">{t('boot.failedTitle')}</p>
          <p className="boot-failed-reason">{t(`boot.reason.${failure as BootFailReason}`)}</p>
          <div className="boot-actions">
            <button type="button" className="ui-button" onClick={onRetry}>
              {t('boot.retry')}
            </button>
            {failure !== 'offline' && (
              <button
                type="button"
                className="ui-button"
                onClick={onBundle}
                disabled={bundleStatus === 'working'}
              >
                {bundleStatus === 'working' ? t('boot.bundleWorking') : t('boot.bundle')}
              </button>
            )}
          </div>
          {bundleStatus === 'ready' && bundlePath && (
            <p className="boot-bundle-result" aria-live="polite">
              {t('boot.bundleReady', { path: bundlePath })}
            </p>
          )}
          {bundleStatus === 'failed' && (
            <p className="boot-bundle-result" aria-live="polite">
              {t('boot.bundleFailed')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
