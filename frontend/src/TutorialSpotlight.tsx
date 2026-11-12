import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import type { TutorialStep } from './tutorialTour.mjs';

type Rect = { readonly left: number; readonly top: number; readonly width: number; readonly height: number };

function targetRect(target: string): Rect | null {
  const element = document.querySelector(`[data-tour="${target}"]`);
  if (!(element instanceof HTMLElement)) return null;
  const box = element.getBoundingClientRect();
  if (box.width === 0 && box.height === 0) return null;
  return { left: box.left, top: box.top, width: box.width, height: box.height };
}

export default function TutorialSpotlight({
  step,
  index,
  total,
  draftText,
  onDraft,
  onSkip,
  onLater,
}: {
  readonly step: TutorialStep;
  readonly index: number;
  readonly total: number;
  readonly draftText: string | null;
  readonly onDraft: ((text: string) => void) | null;
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
          top: rect.top + rect.height + 12 + 220 > window.innerHeight
            ? Math.max(8, rect.top - 232)
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
        {draftText !== null && onDraft !== null && (
          <button type="button" className="tutorial-primary" onClick={() => onDraft(draftText)}>
            {t('tutorial.useDemo')}
          </button>
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
