import type { RuntimeState } from './runtimeLifecycle';
import { useLocale, type I18nKey } from './i18n/index.ts';
import { operatorDetailText } from './RuntimeNavStatus';
import { Button } from './ui/Button';
import { WorkbenchPrompt } from './WorkbenchPrompt';

type ProtectedViewId = 'workspace' | 'results' | 'run' | 'settings';

type RuntimeUnavailableViewProps = {
  readonly view: ProtectedViewId;
  readonly state: Exclude<RuntimeState, 'online'>;
  readonly detail: string;
  readonly busy: boolean;
  readonly onRetry: () => void;
};

type RuntimeUnavailableCopy = {
  readonly kicker: I18nKey;
  readonly title: I18nKey;
  readonly description: I18nKey;
};

const COPY: Readonly<Record<ProtectedViewId, RuntimeUnavailableCopy>> = {
  workspace: { kicker: 'offline.kickerWorkspace', title: 'offline.titleWorkspace', description: 'offline.descWorkspace' },
  results: { kicker: 'offline.kickerResults', title: 'offline.titleResults', description: 'offline.descResults' },
  run: { kicker: 'offline.kickerRun', title: 'offline.titleRun', description: 'offline.descRun' },
  settings: { kicker: 'offline.kickerSettings', title: 'offline.titleSettings', description: 'offline.descSettings' },
};

export function RuntimeUnavailableView({ view, state, detail, busy, onRetry }: RuntimeUnavailableViewProps) {
  const { t } = useLocale();
  const copy = COPY[view];
  const connectionLabel = state === 'offline' ? t('offline.offline') : t('offline.connecting');
  return (
    <section className="runtime-unavailable-view">
      <WorkbenchPrompt
        kicker={t(copy.kicker)}
        title={t(copy.title)}
        description={t(copy.description)}
        contextLabel={t('offline.connectionState')}
        contextValue={connectionLabel}
        contextDetail={operatorDetailText(t, detail)}
      >
        <ol className="workbench-prompt-steps" aria-label={t('offline.boundaryAria')}>
          <li><span>01</span><div><strong>{t('offline.navAvailable')}</strong><em>{t('offline.navAvailableDetail')}</em></div></li>
          <li><span>02</span><div><strong>{t('offline.pauseTitle')}</strong><em>{t('offline.pauseDetail')}</em></div></li>
        </ol>
        <div className="workbench-prompt-footer">
          <Button variant="primary" onClick={onRetry} busy={busy} busyLabel={t('offline.connecting')}>{t('offline.retry')}</Button>
          <span className="workbench-prompt-note">{t('offline.stillOpen')}</span>
        </div>
      </WorkbenchPrompt>
    </section>
  );
}
