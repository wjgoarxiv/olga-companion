import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { resolveTourTarget, type TutorialPath, type TutorialStep } from './tutorialTour.mjs';

type Rect = { readonly left: number; readonly top: number; readonly width: number; readonly height: number };

function hasSize(element: HTMLElement): boolean {
  const box = element.getBoundingClientRect();
  return box.width !== 0 || box.height !== 0;
}

function elementRect(element: HTMLElement): Rect {
  const box = element.getBoundingClientRect();
  return { left: box.left, top: box.top, width: box.width, height: box.height };
}

function targetRect(target: string): Rect | null {
  const element = resolveTourTarget(
    target,
    (selector) => {
      const found = document.querySelector(selector);
      return found instanceof HTMLElement ? found : null;
    },
    hasSize,
  );
  return element === null ? null : elementRect(element);
}

const BUBBLE_HEIGHT = 340;

export function TutorialResumeChip({ index, onResume }: { readonly index: number; readonly onResume: () => void }) {
  const { t } = useLocale();
  const [anchor, setAnchor] = useState<Rect | null>(null);

  useEffect(() => {
    const update = () => {
      const button = document.querySelector('.tutorial-btn');
      setAnchor(button instanceof HTMLElement && hasSize(button) ? elementRect(button) : null);
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const style = anchor === null
    ? undefined
    : { top: anchor.top + anchor.height + 6, right: Math.max(8, window.innerWidth - anchor.left - anchor.width) };
  return (
    <button type="button" className="tutorial-resume" style={style} onClick={onResume}>
      {t('tutorial.resume', { n: index + 1 })}
    </button>
  );
}

export default function TutorialSpotlight({
  step,
  index,
  total,
  path,
  statusLine,
  actionLabel,
  actionBusy,
  actionError,
  onAction,
  onChoosePath,
  onSkip,
  onLater,
}: {
  readonly step: TutorialStep;
  readonly index: number;
  readonly total: number;
  readonly path: TutorialPath;
  /** The step-bar status line this step ends with, already translated. */
  readonly statusLine: string;
  readonly actionLabel: string | null;
  readonly actionBusy: boolean;
  readonly actionError: string;
  readonly onAction: (() => void) | null;
  /** Given only while the path can still change (the first two steps). */
  readonly onChoosePath: ((path: TutorialPath) => void) | null;
  readonly onSkip: () => void;
  readonly onLater: () => void;
}) {
  const { t } = useLocale();
  const [rect, setRect] = useState<Rect | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const update = () => setRect(targetRect(step.target));
    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [step.target]);

  useEffect(() => {
    dialogRef.current?.focus({ preventScroll: true });
  }, [step.id]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onLater();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onLater]);

  const bubbleStyle =
    rect === null
      ? undefined
      : {
          left: Math.max(8, Math.min(rect.left, window.innerWidth - 336)),
          top: rect.top + rect.height + 12 + BUBBLE_HEIGHT > window.innerHeight
            ? Math.max(8, rect.top - BUBBLE_HEIGHT - 12)
            : rect.top + rect.height + 12,
        };

  return (
    <div className="tutorial-layer">
      <div className="tutorial-veil" aria-hidden="true" />
      {rect !== null && (
        <div
          className="tutorial-ring"
          aria-hidden="true"
          style={{ left: rect.left - 6, top: rect.top - 6, width: rect.width + 12, height: rect.height + 12 }}
        />
      )}
      <div
        ref={dialogRef}
        className={`tutorial-bubble${rect === null ? ' is-centered' : ''}`}
        role="dialog"
        aria-label={t(`${step.textKey}.title`)}
        tabIndex={-1}
        style={bubbleStyle}
      >
        <p className="tutorial-progress">{t('tutorial.progress', { n: index + 1 })}</p>
        <h2>{t(`${step.textKey}.title`)}</h2>
        <p>{t(`${step.textKey}.body`)}</p>
        <dl className="tutorial-facts">
          <dt>{t('tutorial.label.where')}</dt>
          <dd>{t(`${step.textKey}.where`)}</dd>
          <dt>{t('tutorial.label.done')}</dt>
          <dd>{t(`${step.textKey}.done`)}</dd>
          <dt>{t('tutorial.label.status')}</dt>
          <dd className="tutorial-status">{statusLine}</dd>
        </dl>
        {actionLabel !== null && onAction !== null && (
          <button type="button" className="tutorial-primary" onClick={onAction} disabled={actionBusy}>
            {actionBusy ? t('examples.installing') : actionLabel}
          </button>
        )}
        {actionError !== '' && <p role="alert">{actionError}</p>}
        {onChoosePath !== null && (
          <div className="tutorial-choices" role="group" aria-label={t('tutorial.path.label')}>
            {(['demo', 'pipe'] as const).map((choice) => (
              <button
                key={choice}
                type="button"
                className="tutorial-choice"
                aria-pressed={path === choice}
                onClick={() => onChoosePath(choice)}
              >
                {t(`tutorial.path.${choice}`)}
              </button>
            ))}
          </div>
        )}
        <div className="tutorial-bubble-actions">
          <button type="button" className="tutorial-ghost" onClick={onLater}>
            {t('tutorial.later')}
          </button>
          <button type="button" className="tutorial-ghost" onClick={onSkip}>
            {t('tutorial.end')}
          </button>
        </div>
      </div>
    </div>
  );
}
