import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from './ui/Button';
import { fetchXaiLoginStatus, logoutXai, startXaiLogin } from './xaiApi';
import { XAI_POLL_MS, isTerminalXaiState } from './xaiConnect';
import { useLocale, type I18nKey } from './i18n/index.ts';

type XaiView = {
  readonly state: string;
  readonly message?: string;
  readonly code?: string;
  readonly uri?: string;
};

const XAI_TITLE_KEYS: Record<string, I18nKey> = {
  idle: 'xai.titleIdle',
  starting: 'xai.titleStarting',
  pending: 'xai.titlePending',
  connected: 'xai.titleConnected',
  denied: 'xai.titleDenied',
  expired: 'xai.titleExpired',
  error: 'xai.titleError',
};

const XAI_ACTION_KEYS: Record<string, I18nKey> = {
  pending: 'xai.actionRestart',
  connected: 'xai.actionDisconnect',
};

export default function XaiConnect({ onConnected }: { onConnected: () => void }) {
  const [view, setView] = useState<XaiView>({ state: 'idle' });
  const timer = useRef<number | null>(null);
  const { t } = useLocale();

  const stop = useCallback(() => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
  }, []);

  const apply = useCallback((status: Awaited<ReturnType<typeof fetchXaiLoginStatus>>) => {
    setView((prev) => ({
      state: status.state,
      message: status.message,
      code: status.user_code ?? prev.code,
      uri: status.verification_uri_complete ?? status.verification_uri ?? prev.uri,
    }));
    if (isTerminalXaiState(status.state)) {
      stop();
      if (status.state === 'connected') onConnected();
    }
  }, [onConnected, stop]);

  const poll = useCallback(() => {
    stop();
    timer.current = window.setInterval(() => {
      fetchXaiLoginStatus().then(apply).catch(() => undefined);
    }, XAI_POLL_MS);
  }, [apply, stop]);

  useEffect(() => {
    fetchXaiLoginStatus().then((status) => {
      apply(status);
      if (status.state === 'pending') poll();
    }).catch(() => undefined);
    return stop;
  }, [apply, poll, stop]);

  async function connect() {
    setView({ state: 'starting' });
    try {
      const started = await startXaiLogin();
      setView({ state: 'pending', code: started.user_code, uri: started.verification_uri_complete });
      poll();
    } catch {
      setView({ state: 'loginFailed', message: undefined });
    }
  }

  async function disconnect() {
    stop();
    try {
      apply(await logoutXai());
      onConnected();
    } catch {
      setView({ state: 'logoutFailed', message: undefined });
    }
  }

  const title = view.state === 'loginFailed'
    ? t('xai.loginFailed')
    : view.state === 'logoutFailed'
      ? t('xai.logoutFailed')
      : view.state === 'error' && view.message
        ? view.message
        : t(XAI_TITLE_KEYS[view.state] ?? 'xai.titleIdle');
  const action = t(XAI_ACTION_KEYS[view.state] ?? 'xai.actionConnect');
  const connected = view.state === 'connected';
  return (
    <div className="xai-connect" aria-label={t('xai.aria')}>
      {view.state !== 'idle' && (
        <div className="operation-status" role="status">
          <div className="operation-status-copy">
            <strong>{title}</strong>
          </div>
        </div>
      )}
      {view.state === 'pending' && view.code && (
        <div className="xai-connect-code">
          <code aria-label={t('xai.codeAria')}>{view.code}</code>
          {view.uri && (
            <a href={view.uri} target="_blank" rel="noopener noreferrer">{t('xai.openBrowser')}</a>
          )}
          {view.uri && <span className="xai-connect-url">{view.uri}</span>}
        </div>
      )}
      <Button
        variant="secondary"
        busy={view.state === 'starting'}
        busyLabel={t('xai.starting')}
        onClick={connected ? disconnect : connect}
      >
        {action}
      </Button>
    </div>
  );
}
