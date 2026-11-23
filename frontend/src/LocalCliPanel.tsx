import { useCallback, useEffect, useState } from 'react';
import { Button } from './ui/Button';
import { checkLocalCli, fetchLocalCliStatus, type LocalCliResult } from './localCliApi';
import { localCliBillingKey, localCliMessage, localCliView } from './localCliConnect';
import { useLocale, type I18nKey } from './i18n/index.ts';

const CLI_COMMAND = 'claude';

export default function LocalCliPanel({ onChanged }: { onChanged: () => void }) {
  const { locale, t } = useLocale();
  const [status, setStatus] = useState<LocalCliResult | null>(null);
  const [check, setCheck] = useState<LocalCliResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(async (fresh = false) => {
    setFailed(false);
    try {
      setStatus(await fetchLocalCliStatus(fresh));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runCheck() {
    setBusy(true);
    setFailed(false);
    try {
      setCheck(await checkLocalCli());
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  async function recheck() {
    setCheck(null);
    setStatus(null);
    await refresh(true);
    onChanged();
  }

  const view = localCliView(status, check);
  const version = check?.version || status?.version || '';
  const title = view.titleKey
    ? t(view.titleKey as I18nKey, { version })
    : localCliMessage(view.state === 'not_found' ? status : check, locale);
  const billingKey = view.state === 'ready' ? localCliBillingKey(check?.billing) : null;
  const canCheck = view.state === 'found' || view.state === 'needs_sign_in' || view.state === 'problem' || view.state === 'ready';

  return (
    <div className="local-cli" aria-label={t('localCli.aria')}>
      <p className="local-cli-note">{t('localCli.description')}</p>
      <div className="operation-status" role="status" data-state={view.state}>
        <div className="operation-status-copy">
          <strong>{failed ? t('localCli.requestFailed') : title}</strong>
          {billingKey && <span className="local-cli-billing">{t(billingKey as I18nKey)}</span>}
        </div>
      </div>
      {view.stepKey && <p className="local-cli-step">{t(view.stepKey as I18nKey)}</p>}
      {view.showCommand && (
        <p className="local-cli-command">
          <span>{t('localCli.commandLabel')}</span> <code>{CLI_COMMAND}</code>
        </p>
      )}
      <p className="local-cli-wsl">{t('localCli.wslNote')}</p>
      <div className="local-cli-actions">
        {canCheck && (
          <Button variant="secondary" busy={busy} busyLabel={t('localCli.checking')} onClick={runCheck}>
            {t('localCli.check')}
          </Button>
        )}
        <Button variant="quiet" onClick={recheck}>{t('localCli.recheck')}</Button>
      </div>
    </div>
  );
}
