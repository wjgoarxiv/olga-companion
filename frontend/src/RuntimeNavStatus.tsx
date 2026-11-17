import type { RuntimeState } from './runtimeLifecycle';
import { useLocale, type I18nKey, type TranslateFn } from './i18n/index.ts';
import { Button } from './ui/Button';

type RuntimeNavStatusProps = {
  readonly state: RuntimeState;
  readonly detail: string;
  readonly busy: boolean;
  readonly onRetry: () => void;
};

type RuntimeNavPresentation = {
  readonly tone: 'busy' | 'error';
  readonly titleKey: I18nKey;
  readonly stateKey: I18nKey;
  readonly role: 'status' | 'alert';
  readonly live: 'polite' | 'assertive';
};

function assertNever(value: never): never {
  throw new TypeError(`Unsupported runtime navigation state: ${String(value)}`);
}

/** Operator messages are a stable English contract from the runtime boundary
 *  (pinned verbatim by runtime-recovery tests); the views below resolve them
 *  through the dictionary so the English twin stays available per locale. */
const OPERATOR_MESSAGE_KEYS: Readonly<Record<string, I18nKey>> = {
  'Connecting to local runtime': 'runtime.msgConnecting',
  'Local runtime is offline': 'runtime.msgOffline',
  'Local session expired': 'runtime.msgSessionExpired',
  'Local runtime is unavailable': 'runtime.msgUnavailable',
};

export function operatorDetailText(t: TranslateFn, detail: string): string {
  const key = OPERATOR_MESSAGE_KEYS[detail];
  return key ? t(key) ?? detail : detail;
}

function presentRuntimeState(state: RuntimeState): RuntimeNavPresentation | null {
  switch (state) {
    case 'online':
      return null;
    case 'connecting':
    case 'reconnecting':
      return { tone: 'busy', titleKey: 'runtime.connectingTitle', stateKey: 'runtime.connectingState', role: 'status', live: 'polite' };
    case 'offline':
      return { tone: 'error', titleKey: 'runtime.offlineTitle', stateKey: 'runtime.offlineState', role: 'alert', live: 'assertive' };
    default:
      return assertNever(state);
  }
}

export function RuntimeNavStatus({ state, detail, busy, onRetry }: RuntimeNavStatusProps) {
  const { t } = useLocale();
  const presentation = presentRuntimeState(state);
  if (!presentation) return null;
  return (
    <div
      className={`runtime-nav-status runtime-nav-status-${presentation.tone}`}
      role={presentation.role}
      aria-live={presentation.live}
      aria-label={`${t(presentation.titleKey)}. ${detail}`}
    >
      <span className="runtime-nav-status-signal" aria-hidden="true" />
      <span className="runtime-nav-status-copy" aria-hidden="true">
        <span className="runtime-nav-status-label">{t('runtime.label')}</span>
        <strong>{t(presentation.stateKey)}</strong>
      </span>
      <Button className="runtime-nav-status-retry" variant="secondary" onClick={onRetry} busy={busy} busyLabel={t('runtime.retrying')} aria-label={t('runtime.retryAria')}>
        {t('runtime.retry')}
      </Button>
    </div>
  );
}
