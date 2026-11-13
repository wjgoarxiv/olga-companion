import { useEffect, type ReactElement } from 'react';
import { useLocale } from './i18n/index.ts';
import { FlowScene, LifecycleWindow, LogLine, type LogState } from './LifecycleWindow.tsx';
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
  const current = STAGE_ORDER.indexOf(stage);
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
  const lineState = (index: number): LogState => {
    if (index < current || leaving) return 'done';
    if (index > current) return 'todo';
    return failed ? 'failed' : 'current';
  };
  return (
    <div
      className={leaving ? 'boot-overlay is-leaving' : 'boot-overlay'}
      role={failed ? 'alert' : 'status'}
      aria-label={t('boot.loading')}
    >
      <LifecycleWindow process="olga-companion-sidecar">
        <FlowScene result={failed ? 'fail' : leaving ? 'ok' : 'flowing'} />
        <ol className="lc-log">
          {STAGE_ORDER.map((name, index) => (
            <LogLine key={name} state={lineState(index)}>
              {t(`boot.stage.${name}`)}
            </LogLine>
          ))}
        </ol>
        {!failed && (
          <div
            className="lc-bar"
            role="progressbar"
            aria-label={t('boot.loading')}
            aria-valuemin={0}
            aria-valuemax={STAGE_ORDER.length}
            aria-valuenow={current + 1}
          >
            <span style={{ transform: `scaleX(${(current + 1) / STAGE_ORDER.length})` }} />
          </div>
        )}
        {failed && (
          <div className="boot-failed">
            <p className="boot-failed-title">{t('boot.failedTitle')}</p>
            <p className="boot-failed-reason">{t(`boot.reason.${failure as BootFailReason}`)}</p>
            <div className="lc-actions">
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
      </LifecycleWindow>
    </div>
  );
}
