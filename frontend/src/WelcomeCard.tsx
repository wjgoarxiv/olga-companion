import { useLocale } from './i18n/index.ts';

export default function WelcomeCard({
  onStart,
  onLater,
}: {
  readonly onStart: () => void;
  readonly onLater: () => void;
}) {
  const { t } = useLocale();
  return (
    <section className="tutorial-welcome" aria-label={t('tutorial.welcome.title')}>
      <h2>{t('tutorial.welcome.title')}</h2>
      <p>{t('tutorial.welcome.body')}</p>
      <div className="tutorial-welcome-actions">
        <button type="button" className="tutorial-primary" onClick={onStart}>
          {t('tutorial.start')}
        </button>
        <button type="button" className="tutorial-ghost" onClick={onLater}>
          {t('tutorial.later')}
        </button>
      </div>
    </section>
  );
}
