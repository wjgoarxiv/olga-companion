import type { ReactElement } from 'react';
import { useLocale } from './i18n/index.ts';
import { SHUTDOWN_STAGES, stageProgress } from './shutdownFlow.mjs';
import './styles/boot.css';

export type ShutdownPhase = 'idle' | 'confirm' | 'saving' | 'stopping' | 'closing' | 'closed' | 'failed';

export default function ShutdownOverlay({
  phase,
  failureReason,
  onConfirmQuit,
  onStay,
  onRetry,
}: {
  phase: ShutdownPhase;
  failureReason: string | null;
  onConfirmQuit: () => void;
  onStay: () => void;
  onRetry: () => void;
}): ReactElement | null {
  const { t } = useLocale();
  if (phase === 'idle' || phase === 'closed') return null;
  const failed = phase === 'failed';
  const current = failed ? null : SHUTDOWN_STAGES.indexOf(phase);
  return (
    <div className="shutdown-overlay" role={phase === 'confirm' ? 'alertdialog' : 'status'}
      aria-label={t('shutdown.title')}
      aria-modal={phase === 'confirm' ? true : undefined}>
      <div className="shutdown-card">
        <p className="shutdown-title">{t('shutdown.title')}</p>
        {phase === 'confirm' ? (
          <>
            <p className="shutdown-confirm-title">{t('shutdown.confirmTitle')}</p>
            <p className="shutdown-confirm-body">{t('shutdown.confirmBody')}</p>
            <div className="shutdown-actions">
              <button type="button" className="ui-button shutdown-quit" onClick={onConfirmQuit}>
                {t('shutdown.confirmQuit')}
              </button>
              <button type="button" className="ui-button" onClick={onStay} autoFocus>
                {t('shutdown.confirmStay')}
              </button>
            </div>
          </>
        ) : (
          <>
            <ol className="shutdown-stages">
              {SHUTDOWN_STAGES.map((stage, index) => (
                <li
                  key={stage}
                  aria-current={index === current ? 'step' : undefined}
                  className={index === current ? 'is-current' : index < (current ?? 0) ? 'is-done' : ''}
                >
                  {t(`shutdown.stage.${stage}`)}
                </li>
              ))}
            </ol>
            <div
              className="shutdown-bar"
              role="progressbar"
              aria-label={t('shutdown.title')}
              aria-valuemin={0}
              aria-valuemax={SHUTDOWN_STAGES.length}
              aria-valuenow={failed ? 0 : (current ?? 0) + 1}
            >
              <span style={{ transform: `scaleX(${failed ? 0 : stageProgress(SHUTDOWN_STAGES[Math.max(0, current ?? 0)])})` }} />
            </div>
            {failed && (
              <>
                <p className="shutdown-error" role="alert">{t('shutdown.failed')}{failureReason ? ` (${failureReason})` : ''}</p>
                <div className="shutdown-actions">
                  <button type="button" className="ui-button" onClick={onRetry}>
                    {t('boot.retry')}
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
