import { useEffect, useState } from 'react';
import { Button } from '../ui/Button';
import { Popover } from '../ui/Popover';
import { operatorDetailText } from '../RuntimeNavStatus';
import { CAPABILITY_LABEL_KEYS, CAPABILITY_LABELS, capabilityRows } from '../EnvDrawer';
import type { RuntimeState } from '../runtimeLifecycle';
import type { Health } from '../types';
import { useLocale } from '../i18n/index.ts';
import type { WorkbenchView } from './useWorkbenchLayout';
import UpdateNotice from '../UpdateNotice';
import { getProxyStatus, refresh as refreshProxyStatus, subscribe as subscribeProxyStatus } from '../proxyStatus.mjs';

function stateKey(state: RuntimeState): 'shell.runtimeOnline' | 'runtime.connectingState' | 'runtime.offlineState' {
  if (state === 'online') return 'shell.runtimeOnline';
  if (state === 'connecting' || state === 'reconnecting') return 'runtime.connectingState';
  return 'runtime.offlineState';
}

export default function StatusBar({
  view,
  state,
  detail,
  busy,
  retryingLabel,
  onRetry,
  health,
  modelLabel,
  onOpenUpdates,
}: {
  readonly view: WorkbenchView;
  readonly state: RuntimeState;
  readonly detail: string;
  readonly busy: boolean;
  readonly retryingLabel: string | undefined;
  readonly onRetry: () => void;
  readonly health: Health | null;
  readonly modelLabel: string;
  readonly onOpenUpdates: () => void;
}) {
  const { t, locale } = useLocale();
  const [open, setOpen] = useState(false);
  const [proxy, setProxy] = useState<{ enabled: boolean; ok: boolean }>(getProxyStatus());

  useEffect(() => {
    setOpen(false);
  }, [view]);
  useEffect(() => {
    void refreshProxyStatus();
    return subscribeProxyStatus((next) => setProxy(next));
  }, []);
  const caps = capabilityRows(health);
  const online = state === 'online';
  const label = `${t('shell.runtimeItem') ?? 'Runtime'} · ${t(stateKey(state))}`;

  return (
    <footer className="wb-status" aria-label={t('shell.statusLabel')}>
      <button
        type="button"
        className={`wb-status-runtime${online ? ' is-online' : ''}`}
        aria-expanded={open}
        aria-controls="runtime-status-popover"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="wb-heartbeat" aria-hidden="true" />
        <span className="wb-status-text">{label}</span>
      </button>
      <span className="wb-status-model" aria-label={t('status.modelAria', { model: modelLabel }) ?? `Language model: ${modelLabel}`}>
        <span className="wb-status-model-kicker">{t('status.aiModel')}</span>
        <strong className="wb-status-model-name">{modelLabel}</strong>
      </span>
      {proxy.enabled && proxy.ok && (
        <span className="wb-status-proxy" aria-label={t('settings.statusProxyOn')} title={t('settings.statusProxyOn')}>
          {t('settings.statusProxyOn')}
        </span>
      )}
      <button
        type="button"
        className="wb-status-locale"
        aria-label={t('shell.cmdSwitchLanguage')}
        title={t('shell.cmdSwitchLanguage')}
        onClick={() => setOpen(true)}
      >
        {locale === 'ko' ? t('language.korean') : t('language.english')}
      </button>
      {open && (
        <div id="runtime-status-popover" className="wb-status-popover-slot">
          <Popover open={open} onClose={() => setOpen(false)} label={t('shell.statusLabel')}>
            <p className="wb-status-head">{t('shell.runtimeItem')}</p>
            <p className="wb-status-row">
              <span>{t('runtime.label')}</span>
              <strong>{t(stateKey(state))}</strong>
            </p>
            <p className="wb-status-row">
              <span>{t('shell.sidecar')}</span>
              <strong>{operatorDetailText(t, detail)}</strong>
            </p>
            <p className="wb-status-row">
              <span>{t('status.aiModel')}</span>
              <strong>{modelLabel}</strong>
            </p>
            <p className="wb-status-row">
              <span>{t('language.title')}</span>
              <strong>{locale === 'ko' ? t('language.korean') : t('language.english')}</strong>
            </p>
            {caps.length > 0 && (
              <ul className="wb-status-caps">
                {caps.map(([name, cap]) => (
                  <li key={name} className={cap.enabled ? 'capability enabled' : 'capability gated'}>
                    <span>{(CAPABILITY_LABEL_KEYS[name] ? t(CAPABILITY_LABEL_KEYS[name]) : null) ?? CAPABILITY_LABELS[name] ?? name.replaceAll('_', ' ')}</span>
                    <strong>{cap.enabled ? t('env.available') : t('env.gated')}</strong>
                    {!cap.enabled && cap.reason && <small className="capability-reason">{cap.reason}</small>}
                  </li>
                ))}
              </ul>
            )}
            {!online && (
              <Button variant="secondary" onClick={() => { onRetry(); setOpen(false); }} busy={busy} busyLabel={retryingLabel}>
                {t('runtime.retry')}
              </Button>
            )}
          </Popover>
        </div>
      )}
      <UpdateNotice onOpenSettings={onOpenUpdates} />
    </footer>
  );
}
