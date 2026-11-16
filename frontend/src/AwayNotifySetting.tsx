import { useState, type ReactElement } from 'react';
import { useLocale } from './i18n/index.ts';
import { loadAwayNotifyEnabled, saveAwayNotifyEnabled } from './awayNotify.mjs';

/** Settings → General toggle: notify only while the operator is in another
 *  window. Lives here so SettingsView keeps no raw inputs. */
export default function AwayNotifySetting(): ReactElement {
  const { t } = useLocale();
  const [notifyAway, setNotifyAway] = useState(loadAwayNotifyEnabled);
  return (
    <article className="settings-card notify-card">
      <div>
        <h3 className="settings-h">{t('settings.notifyAway')}</h3>
        <p className="settings-note">{t('settings.notifyAwayNote')}</p>
      </div>
      <label className="notify-control">
        <input
          type="checkbox"
          checked={notifyAway}
          onChange={(event) => {
            const next = event.target.checked;
            setNotifyAway(next);
            saveAwayNotifyEnabled(next);
          }}
        />
        <span>{t('settings.notifyAway')}</span>
      </label>
    </article>
  );
}
