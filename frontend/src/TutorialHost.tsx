import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import type { TimelineItem } from './timeline.ts';
import { collectCompletedRunIds, collectLaunchedRunIds } from './runCompletion.ts';
import { runDetect } from './runApi.ts';
import { OPEN_ARTIFACT_IN_RESULTS_EVENT } from './artifactNavigation.ts';
import { CASE_VALIDATED_EVENT } from './caseReview.ts';
import { DEMO_EXAMPLE_ID, EXAMPLE_INSTALLED_EVENT, exampleErrorKey, installExample, loadRememberedExample, type ExampleInstall } from './examplesApi.ts';
import { subscribeRunObservations } from './taskbarRunFeed.mjs';
import { demoRunSignal } from './tutorialRunWatch.mjs';
import {
  TUTORIAL_CHANGE_EVENT,
  TUTORIAL_EVENTS,
  TUTORIAL_OPEN_EVENT,
  TUTORIAL_STEPS,
  advanceTutorial,
  freshRunIds,
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
  stepAction,
  tutorialStepSatisfied,
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

export function applyTutorialCommand(
  kind: 'focus-workspace' | 'validate' | 'show-problems' | 'open-run' | 'open-results',
  actions: {
    readonly runCommand: (id: 'validate' | 'open-run') => void;
    readonly selectView: (next: 'workspace' | 'results' | 'run' | 'settings') => void;
    readonly setPanelOpen: (open: boolean) => void;
    readonly setPanelTab: (tab: 'problems' | 'console' | 'outputs') => void;
  },
): void {
  if (kind === 'focus-workspace') {
    const target = document.querySelector('[data-tour="workspace"]');
    if (target instanceof HTMLElement) target.focus();
    return;
  }
  if (kind === 'validate') {
    actions.runCommand('validate');
    return;
  }
  if (kind === 'show-problems') {
    actions.selectView('workspace');
    actions.setPanelOpen(true);
    actions.setPanelTab('problems');
    return;
  }
  if (kind === 'open-run') {
    actions.runCommand('open-run');
    return;
  }
  actions.selectView('results');
}

export default function TutorialHost({
  workspaceRoot,
  activeCaseName,
  timeline,
  resultsOpen,
  validationVisible,
  ready,
  onCommand,
}: {
  readonly workspaceRoot: string;
  readonly activeCaseName: string | null;
  readonly timeline: readonly TimelineItem[];
  readonly resultsOpen: boolean;
  readonly validationVisible: boolean;
  readonly ready: boolean;
  readonly onCommand: (kind: 'focus-workspace' | 'validate' | 'show-problems' | 'open-run' | 'open-results') => void;
}) {
  const { t } = useLocale();
  const [tutorial, setTutorial] = useState<TutorialState>(() => loadTutorialState());
  const [resumeAcknowledged, setResumeAcknowledged] = useState<boolean>(() => loadTutorialState().status !== 'active');
  const [artifactOpened, setArtifactOpened] = useState(false);
  const [olgaDetected, setOlgaDetected] = useState<boolean | null>(null);
  const [celebration, setCelebration] = useState<'done' | 'no-olga' | null>(null);
  const [installedCaseName, setInstalledCaseName] = useState<string | null>(null);
  const [validatedCaseName, setValidatedCaseName] = useState<string | null>(null);
  const [validationOk, setValidationOk] = useState(false);
  const [readRequested, setReadRequested] = useState(false);
  const [resultsRequested, setResultsRequested] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const detectAttemptedRef = useRef(false);
  const baselineRef = useRef<{ stepId: string; launched: Set<string>; finished: Set<string>; sawResults: boolean; sawPanel: boolean }>({
    stepId: '', launched: new Set(), finished: new Set(), sawResults: false, sawPanel: false,
  });
  const watchedRunRef = useRef<string | null>(null);
  const viewLaunchedRef = useRef<Set<string>>(new Set());
  const viewFinishedRef = useRef<Set<string>>(new Set());
  const [runWatchVersion, setRunWatchVersion] = useState(0);
  const previousStatusRef = useRef(tutorial.status);
  const tutorialRef = useRef(tutorial);
  tutorialRef.current = tutorial;
  const opened = resultsOpen || artifactOpened;

  useEffect(() => {
    const remembered = loadRememberedExample(undefined, workspaceRoot);
    setInstalledCaseName(
      remembered?.demo === true && remembered.id === DEMO_EXAMPLE_ID ? remembered.caseName : null,
    );
  }, [workspaceRoot]);

  useEffect(() => {
    return subscribeRunObservations((observation) => {
      const signal = demoRunSignal(observation, installedCaseName);
      if (signal === null) return;
      if (signal.started) viewLaunchedRef.current.add(signal.runId);
      if (signal.finished) viewFinishedRef.current.add(signal.runId);
      setRunWatchVersion((version) => version + 1);
    });
  }, [installedCaseName]);

  useEffect(() => {
    const onOpen = () => {
      setResumeAcknowledged(true);
      setCelebration(null);
      if (tutorialRef.current.status === 'done' || tutorialRef.current.status === 'skipped') {
        setValidatedCaseName(null);
        setValidationOk(false);
      }
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
    function onInstalled(event: Event) {
      if (!(event instanceof CustomEvent)) return;
      const detail = event.detail as Partial<ExampleInstall> | null;
      if (detail?.demo === true && detail.id === DEMO_EXAMPLE_ID && typeof detail.case_name === 'string') {
        setInstalledCaseName(detail.case_name);
        setActionError('');
      }
    }
    window.addEventListener(EXAMPLE_INSTALLED_EVENT, onInstalled);
    return () => window.removeEventListener(EXAMPLE_INSTALLED_EVENT, onInstalled);
  }, []);

  useEffect(() => {
    function onValidated(event: Event) {
      if (!(event instanceof CustomEvent)) return;
      const detail = event.detail as { caseName?: unknown; valid?: unknown } | null;
      if (!detail || detail.caseName !== installedCaseName) return;
      setValidatedCaseName(typeof detail.caseName === 'string' ? detail.caseName : null);
      setValidationOk(detail.valid === true);
    }
    window.addEventListener(CASE_VALIDATED_EVENT, onValidated);
    return () => window.removeEventListener(CASE_VALIDATED_EVENT, onValidated);
  }, [installedCaseName]);

  useEffect(() => {
    const stepId = tutorial.status === 'active' ? TUTORIAL_STEPS[tutorial.index]?.id ?? '' : '';
    const launchedNow = new Set([...collectLaunchedRunIds(timeline), ...viewLaunchedRef.current]);
    const finishedNow = new Set([...collectCompletedRunIds(timeline), ...viewFinishedRef.current]);
    if (baselineRef.current.stepId !== stepId) {
      baselineRef.current = {
        stepId,
        launched: new Set(launchedNow),
        finished: new Set(finishedNow),
        sawResults: opened,
        sawPanel: validationVisible,
      };
      if (stepId !== 'run' && stepId !== 'run-progress') watchedRunRef.current = null;
      setReadRequested(false);
      setResultsRequested(false);
    }
    const baseline = baselineRef.current;
    const matchesCase = Boolean(installedCaseName) && activeCaseName === installedCaseName;
    const newLaunched = freshRunIds(launchedNow, baseline.launched);
    if (matchesCase && newLaunched.length > 0 && watchedRunRef.current === null) {
      watchedRunRef.current = newLaunched[0];
    }
    const runStartedForCase = matchesCase && newLaunched.length > 0;
    const runFinishedForCase = matchesCase && watchedRunRef.current !== null
      && finishedNow.has(watchedRunRef.current);
    const validationRead = validationOk && validatedCaseName === installedCaseName && validationVisible
      && (readRequested || !baseline.sawPanel);
    const resultsOpenedForCase = matchesCase && opened && (resultsRequested || !baseline.sawResults);
    const facts = {
      workspaceRoot,
      activeCaseName,
      installedCaseName,
      validatedCaseName,
      validationOk,
      validationRead,
      runStartedForCase,
      runFinishedForCase,
      resultsOpenedForCase,
    };
    const step = tutorial.status === 'active' ? TUTORIAL_STEPS[tutorial.index] : null;
    if (step === null || !tutorialStepSatisfied(step.id, facts)) return;
    setTutorial((previous) => advanceTutorial(previous, step.event));
  }, [tutorial.status, tutorial.index, workspaceRoot, activeCaseName, timeline, validationVisible, opened, installedCaseName, validatedCaseName, validationOk, readRequested, resultsRequested, runWatchVersion]);

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
          actionLabel={(() => {
            const action = stepAction(step.id);
            return action === null ? null : t(action.labelKey);
          })()}
          actionBusy={actionBusy}
          actionError={actionError}
          onAction={() => {
            const action = stepAction(step.id);
            if (action === null) return;
            setActionError('');
            if (action.kind === 'install-demo') {
              setActionBusy(true);
              void installExample(DEMO_EXAMPLE_ID)
                .catch((cause: unknown) => {
                  const message = cause instanceof Error ? cause.message : '';
                  setActionError(t(exampleErrorKey(message)));
                })
                .finally(() => setActionBusy(false));
              return;
            }
            if (action.kind === 'show-problems') setReadRequested(true);
            if (action.kind === 'open-results') setResultsRequested(true);
            onCommand(action.kind);
          }}
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
