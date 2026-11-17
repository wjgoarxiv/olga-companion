import { useLocale } from './i18n/index.ts';
import { rememberSettingsSection } from './SettingsView';
import { requestOpenUpdates } from './updateAutoCheck.mjs';
import { useLaunchUpdateCheck } from './useLaunchUpdateCheck';

/**
 * Tells the user that the launch check found a newer version. Its only action opens
 * Settings → Updates; download and install stay there as separate clicks. The live region
 * stays mounted so screen readers announce the notice when it fills.
 */
export default function UpdateNotice({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { t } = useLocale();
  const { version, dismiss } = useLaunchUpdateCheck();
  return (
    <div className="update-notice-live" role="status" aria-live="polite">
      {version && (
        <div className="update-notice">
          <span key={version} className="update-notice-text update-notice-reveal">{t('update.notice', { version })}</span>
          <button
            type="button"
            className="update-notice-open"
            onClick={() => { dismiss(); rememberSettingsSection('updates'); requestOpenUpdates(); onOpenSettings(); }}
          >
            {t('update.noticeOpen')}
          </button>
          <button type="button" className="update-notice-dismiss" onClick={dismiss} aria-label={t('update.noticeDismiss')}>×</button>
        </div>
      )}
    </div>
  );
}
