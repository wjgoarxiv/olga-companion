import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import type { TimelineItem } from './timeline.ts';
import { latestCaseEvidence } from './shell/useStepState.ts';
import { collectCompletedRunIds, collectLaunchedRunIds } from './runCompletion.ts';
import { runDetect } from './runApi.ts';
import { OPEN_ARTIFACT_IN_RESULTS_EVENT } from './artifactNavigation.ts';
import {
  TUTORIAL_CHANGE_EVENT,
  TUTORIAL_EVENTS,
  TUTORIAL_OPEN_EVENT,
  TUTORIAL_STEPS,
  advanceTutorial,
  isTutorialFinished,
  loadTutorialState,
  notifyTutorialChanged,
  pauseTutorial,
  resetTutorial,
  resumeChipPending,
  resumeTutorial,
  saveTutorialState,
  skipTutorial,
  startTutorial,
  type TutorialState,
} from './tutorialTour.mjs';
import { scheduleFocusReturn } from './focusReturn';
import TutorialSpotlight, { TutorialResumeChip } from './TutorialSpotlight.tsx';
import WelcomeCard from './WelcomeCard.tsx';
import './styles/tutorial.css';

export function useTutorialBadge(): boolean {
  const [done, setDone] = useState<boolean>(() => isTutorialFinished(loadTutorialState()));
  useEffect(() => {
    const update = () => setDone(isTutorialFinished(loadTutorialState()));
    window.addEventListener(TUTORIAL_CHANGE_EVENT, update);
    return () => window.removeEventListener(TUTORIAL_CHANGE_EVENT, update);
  }, []);
  return done;
}

function currentStep(state: TutorialState) {
  return state.status === 'active' ? TUTORIAL_STEPS[state.index] ?? null : null;
}

function TutorialEndCard({ variant, onClose }: { readonly variant: 'done' | 'no-olga'; readonly onClose: () => void }) {
  const { t } = useLocale();
  const cardRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const active = document.activeElement;
    const opener = active instanceof HTMLElement && active !== document.body ? active : null;
    // selectView() focuses <main> in its own frame; focusing in a later one keeps the card the owner.
    const frame = requestAnimationFrame(() => cardRef.current?.focus({ preventScroll: true }));
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeRef.current();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('keydown', onKey);
      scheduleFocusReturn(opener, undefined, () => {
        const button = document.querySelector('.tutorial-btn');
        return button instanceof HTMLElement ? button : null;
      });
    };
  }, []);

  const key = variant === 'no-olga' ? 'tutorial.noOlga' : 'tutorial.done';
  return (
    <div className="tutorial-layer">
      <div className="tutorial-veil" aria-hidden="true" />
      <div ref={cardRef} className="tutorial-bubble is-centered" role="dialog" aria-label={t(`${key}.title`)} tabIndex={-1}>
        <h2>{t(`${key}.title`)}</h2>
        <p>{t(`${key}.body`)}</p>
        {variant === 'done' && (
          <ul className="tutorial-examples">
            <li>{t('tutorial.done.example1')}</li>
            <li>{t('tutorial.done.example2')}</li>
          </ul>
        )}
        <div className="tutorial-bubble-actions">
          <button type="button" className="tutorial-primary" onClick={onClose}>
            {t('shell.close')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TutorialHost({
  workspaceRoot,
  activeCaseName,
  timeline,
  resultsOpen,
  validationVisible,
  ready,
  onDraft,
}: {
  readonly workspaceRoot: string;
  readonly activeCaseName: string | null;
  readonly timeline: readonly TimelineItem[];
  readonly resultsOpen: boolean;
  readonly validationVisible: boolean;
  readonly ready: boolean;
  readonly onDraft: (prompt: string) => void;
}) {
  const { t } = useLocale();
  const [tutorial, setTutorial] = useState<TutorialState>(() => loadTutorialState());
  const [resumeAcknowledged, setResumeAcknowledged] = useState<boolean>(() => loadTutorialState().status !== 'active');
  const [artifactOpened, setArtifactOpened] = useState(false);
  const [olgaDetected, setOlgaDetected] = useState<boolean | null>(null);
  const [celebration, setCelebration] = useState<'done' | 'no-olga' | null>(null);
  const detectAttemptedRef = useRef(false);
  const previousStatusRef = useRef(tutorial.status);
  const opened = resultsOpen || artifactOpened;

  useEffect(() => {
    const onOpen = () => {
      setResumeAcknowledged(true);
      setCelebration(null);
      setTutorial((previous) => {
        if (previous.status === 'done' || previous.status === 'skipped') return resetTutorial(previous);
        if (previous.status === 'paused') return resumeTutorial(previous);
        return startTutorial(previous);
      });
    };
    window.addEventListener(TUTORIAL_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(TUTORIAL_OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => {
    function onArtifact() {
      setArtifactOpened(true);
    }
    window.addEventListener(OPEN_ARTIFACT_IN_RESULTS_EVENT, onArtifact);
    return () => window.removeEventListener(OPEN_ARTIFACT_IN_RESULTS_EVENT, onArtifact);
  }, []);

  useEffect(() => {
    const events: string[] = [];
    if (workspaceRoot) events.push(TUTORIAL_EVENTS.WORKSPACE_CHOSEN);
    if (activeCaseName) events.push(TUTORIAL_EVENTS.CASE_CREATED);
    if (latestCaseEvidence(timeline) !== null) events.push(TUTORIAL_EVENTS.VALIDATION_DONE);
    if (validationVisible) events.push(TUTORIAL_EVENTS.VALIDATION_READ);
    if (collectLaunchedRunIds(timeline).size > 0) events.push(TUTORIAL_EVENTS.RUN_STARTED);
    if (collectCompletedRunIds(timeline).size > 0) events.push(TUTORIAL_EVENTS.RUN_FINISHED);
    if (opened) events.push(TUTORIAL_EVENTS.RESULTS_OPENED);
    setTutorial((previous) => {
      let next = previous;
      for (const event of events) {
        const advanced = advanceTutorial(next, event);
        if (advanced.status !== next.status || advanced.index !== next.index
          || advanced.finishedWithoutOlga !== next.finishedWithoutOlga) {
          next = advanced;
        }
      }
      return next === previous ? previous : next;
    });
  }, [tutorial.status, workspaceRoot, activeCaseName, timeline, validationVisible, opened]);

  useEffect(() => {
    saveTutorialState(tutorial);
    notifyTutorialChanged();
    if (tutorial.status === 'done' && previousStatusRef.current === 'active') {
      setCelebration(tutorial.finishedWithoutOlga ? 'no-olga' : 'done');
    } else if (tutorial.status !== 'done') {
      setCelebration(null);
    }
    previousStatusRef.current = tutorial.status;
  }, [tutorial]);

  useEffect(() => {
    if (tutorial.status !== 'active' || TUTORIAL_STEPS[tutorial.index]?.id !== 'run') return;
    if (olgaDetected !== null || detectAttemptedRef.current) return;
    detectAttemptedRef.current = true;
    runDetect()
      .then((detection) => setOlgaDetected(detection.detected))
      .catch(() => undefined);
  }, [tutorial, olgaDetected]);

  useEffect(() => {
    if (tutorial.status === 'active' && TUTORIAL_STEPS[tutorial.index]?.id === 'run' && olgaDetected === false) {
      setTutorial((previous) => advanceTutorial(previous, TUTORIAL_EVENTS.NO_OLGA));
    }
  }, [tutorial, olgaDetected]);

  const step = currentStep(tutorial);
  const chipPending = resumeChipPending(tutorial, resumeAcknowledged);
  if (!ready) return null;
  return (
    <>
      {tutorial.status === 'idle' && (
        <WelcomeCard
          onStart={() => setTutorial((previous) => startTutorial(previous))}
          onLater={() => setTutorial((previous) => pauseTutorial(previous))}
        />
      )}
      {step !== null && chipPending && (
        <TutorialResumeChip index={tutorial.index} onResume={() => setResumeAcknowledged(true)} />
      )}
      {step !== null && !chipPending && (
        <TutorialSpotlight
          step={step}
          index={tutorial.index}
          total={TUTORIAL_STEPS.length}
          draftText={step.id === 'demo-case' ? t('tutorial.demoDraft') : null}
          onDraft={step.id === 'demo-case' ? onDraft : null}
          onSkip={() => setTutorial((previous) => skipTutorial(previous))}
          onLater={() => setTutorial((previous) => pauseTutorial(previous))}
        />
      )}
      {celebration !== null && tutorial.status === 'done' && (
        <TutorialEndCard variant={celebration} onClose={() => setCelebration(null)} />
      )}
    </>
  );
}
