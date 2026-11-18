import { Button } from './ui/Button';
import { Skeleton } from './ui/Skeleton';
import { useLocale } from './i18n/index.ts';
import { WorkbenchPrompt } from './WorkbenchPrompt';

type RootPromptProps = {
  readonly rootLabel: string;
};

type EmptyResultsPromptProps = RootPromptProps & {
  readonly onOpenRun: () => void;
};

type SelectionPromptProps = {
  readonly resultCount: number;
};

export function ResultsLoadingPrompt({ rootLabel }: RootPromptProps) {
  const { t } = useLocale();
  return (
    <WorkbenchPrompt
      className="rv-empty"
      kicker={t('results.loadingKicker')}
      title={t('results.loadingTitle')}
      description={t('results.loadingDesc')}
      contextLabel={t('results.loadingState')}
      contextValue={t('results.loadingValue')}
      contextDetail={rootLabel}
    >
      <Skeleton loadingLabel={t('results.scanning')} lines={4} />
    </WorkbenchPrompt>
  );
}

export function EmptyResultsPrompt({ rootLabel, onOpenRun }: EmptyResultsPromptProps) {
  const { t } = useLocale();
  return (
    <WorkbenchPrompt
      className="rv-empty"
      kicker={t('results.emptyKicker')}
      title={t('results.emptyTitle')}
      description={t('results.emptyDesc')}
      contextLabel={t('results.emptyContext')}
      contextValue={t('results.emptyValue')}
      contextDetail={rootLabel}
    >
      <ol className="workbench-prompt-steps" aria-label={t('results.emptyStepsAria')}>
        <li><span>01</span><div><strong>{t('results.emptyStep1Title')}</strong><em>{t('results.emptyStep1Desc')}</em></div></li>
        <li><span>02</span><div><strong>{t('results.emptyStep2Title')}</strong><em>{t('results.emptyStep2Desc')}</em></div></li>
      </ol>
      <div className="workbench-prompt-footer">
        <Button variant="primary" onClick={onOpenRun}>{t('results.openRun')}</Button>
        <span className="workbench-prompt-note">{t('results.emptyNote')}</span>
      </div>
    </WorkbenchPrompt>
  );
}

export function ResultsSelectionPrompt({ resultCount }: SelectionPromptProps) {
  const { t } = useLocale();
  return (
    <WorkbenchPrompt
      className="rv-selection-state"
      kicker={t('results.pickKicker')}
      title={t('results.pickTitle')}
      description={t('results.pickDesc')}
      contextLabel={t('results.pickContext')}
      contextValue={t(resultCount === 1 ? 'results.pickValueOne' : 'results.pickValueOther', { count: resultCount })}
      contextDetail={t('results.pickDetail')}
    />
  );
}
