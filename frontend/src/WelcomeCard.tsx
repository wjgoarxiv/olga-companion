import { useLocale } from './i18n/index.ts';
import type { TutorialPath } from './tutorialTour.mjs';

export default function WelcomeCard({
  onStart,
  onLater,
}: {
  readonly onStart: (path: TutorialPath) => void;
  readonly onLater: () => void;
}) {
  const { t } = useLocale();
  return (
    <section className="tutorial-welcome" aria-label={t('tutorial.welcome.title')}>
      <h2>{t('tutorial.welcome.title')}</h2>
      <p>{t('tutorial.welcome.body')}</p>
      <div className="tutorial-welcome-paths" role="group" aria-label={t('tutorial.start')}>
        <button type="button" className="tutorial-primary" onClick={() => onStart('demo')}>
          {t('tutorial.path.demo')}
        </button>
        <p className="tutorial-hint">{t('tutorial.path.demoHint')}</p>
        <button type="button" className="tutorial-primary" onClick={() => onStart('pipe')}>
          {t('tutorial.path.pipe')}
        </button>
        <p className="tutorial-hint">{t('tutorial.path.pipeHint')}</p>
        <button type="button" className="tutorial-primary" onClick={() => onStart('edit')}>
          {t('tutorial.path.edit')}
        </button>
        <p className="tutorial-hint">{t('tutorial.path.editHint')}</p>
      </div>
      <div className="tutorial-welcome-actions">
        <button type="button" className="tutorial-ghost" onClick={onLater}>
          {t('tutorial.later')}
        </button>
      </div>
    </section>
  );
}
