import { useEffect, useRef, useState } from 'react';
import { useLocale } from '../i18n/index.ts';
import { SIMULATION_STEPS } from '../simulationSteps';
import { SHELL_COMMANDS } from './commands';
import { SimulationGuideBody } from '../SimulationGuide';
import { CREATE_FLUID_TABLE_EVENT, deriveNextAction, STEPBAR_DETAIL_EVENT, STEPBAR_DETAIL_ID, type NextKind, type StepState } from './useStepState';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';
import type { WorkbenchView } from './useWorkbenchLayout';
import type { WorkspaceContext } from '../workspaceApi';
import type { TimelineItem } from '../timeline';

export type StepCommand = 'validate' | 'preview-run' | 'open-run';

/** Minimal chat surface the step bar drafts through (structural subset of the
    chat controller; mirrors how ChatDockView receives the whole controller). */
export interface StepChat {
  readonly timeline: readonly TimelineItem[];
  readonly input: string;
  readonly busy: boolean;
  readonly setInput: (value: string) => void;
}

export default function StepBar({
  workspace,
  chat,
  online,
  providerReady,
  newCaseStarter,
  onDraftQuestion,
  onNewCase,
  onSelectView,
  onRunCommand,
  onOpenWorkspace,
  onOpenSettings,
  states,
  tabCount,
  intakeEvidence,
  nativeTab = false,
  activeView,
}: {
  readonly workspace: WorkspaceContext;
  readonly chat: StepChat;
  readonly online: boolean;
  readonly providerReady: boolean;
  readonly newCaseStarter: string;
  readonly onDraftQuestion: (prompt: string) => void;
  readonly onNewCase: () => void;
  readonly onSelectView: (view: WorkbenchView) => void;
  readonly onRunCommand: (id: StepCommand) => void;
  readonly onOpenWorkspace: () => void;
  readonly onOpenSettings: () => void;
  readonly states: readonly StepState[];
  readonly tabCount: number;
  readonly intakeEvidence: Record<string, unknown> | null;
  readonly nativeTab?: boolean;
  readonly activeView?: WorkbenchView;
}) {
  const { t } = useLocale();
  // Open popover step id, or null when the row stands alone (D1 default).
  // The strip never changes height; the detail overlays the workbench.
  const [openStep, setOpenStep] = useState<StepState['id'] | null>(null);
  const [anchorLeft, setAnchorLeft] = useState(0);
  const barRef = useRef<HTMLElement | null>(null);
  const stepRefs = useRef(new Map<string, HTMLButtonElement>());
  const triggerRef = useRef<Element | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const activeCaseName = workspace.active.name;
  const hasDraft = chat.input.trim() !== '';
  // W3-L3 registers `create-fluid-table`; until the command exists the ①
  // detail entry and the no-tab next action stay hidden — never a dead button.
  const canCreateFluid = SHELL_COMMANDS.some((command) => (command.id as string) === 'create-fluid-table');
  const createFluidAction = canCreateFluid && tabCount === 0
    ? () => { window.dispatchEvent(new CustomEvent(CREATE_FLUID_TABLE_EVENT)); }
    : undefined;
  const current: StepState = states.find((step) => step.status === 'current')
    ?? states.find((step) => step.status === 'blocked')
    ?? states[states.length - 1];
  const currentIndex = states.indexOf(current);
  const currentRef = useRef(current);
  currentRef.current = current;

  function stepIndex(id: StepState['id']): number {
    return states.findIndex((step) => step.id === id);
  }

  function anchorFor(id: StepState['id']): number {
    const bar = barRef.current;
    const button = stepRefs.current.get(id);
    if (!bar || !button) return 0;
    const barBox = bar.getBoundingClientRect();
    const stepBox = button.getBoundingClientRect();
    return Math.max(0, Math.min(stepBox.left - barBox.left, barBox.width - 432));
  }

  function openPopover(id: StepState['id'], trigger: Element | null) {
    triggerRef.current = trigger ?? document.activeElement;
    setAnchorLeft(anchorFor(id));
    setOpenStep(id);
  }

  function stepTo(id: StepState['id']) {
    setAnchorLeft(anchorFor(id));
    setOpenStep(id);
  }

  function closePopover(restoreFocus: boolean) {
    setOpenStep(null);
    if (restoreFocus) {
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    }
  }

  // The dock link and the palette path open the same popover on the current step.
  useEffect(() => {
    function reopen() {
      openPopover(currentRef.current.id, document.activeElement);
    }
    window.addEventListener(STEPBAR_DETAIL_EVENT, reopen);
    return () => window.removeEventListener(STEPBAR_DETAIL_EVENT, reopen);
  }, [current.id]);

  // Esc closes and returns focus; click-outside closes (step buttons and the
  // dock link toggle through their own handlers instead).
  useEffect(() => {
    if (openStep === null) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') closePopover(true);
    }
    function onPointer(event: PointerEvent) {
      const target = event.target as Element | null;
      if (target && (target.closest('[data-stepbar-popover]') || target.closest('[data-stepbar-steps]') || target.closest('.simulation-guide-link'))) return;
      closePopover(false);
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [openStep]);

  // Scroll fade: the popover sizes to content up to its max-height; when it
  // does scroll, a bottom fade marks the cut instead of a hard clip.
  useEffect(() => {
    const el = popRef.current;
    if (!el || openStep === null) return;
    const update = () => {
      el.dataset.scroll = el.scrollHeight - el.scrollTop - el.clientHeight > 4 ? 'down' : '';
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => {
      el.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [openStep]);

  function reasonText(step: StepState): string | null {
    if (step.reason === 'noTab') return t('stepbar.blockedNoTab');
    if (step.reason === 'errors') return t('stepbar.blockedErrors', { count: step.errorCount });
    if (step.reason === 'noWorkspace') return t('stepbar.blockedNoWorkspace');
    if (step.reason === 'running') return t('stepbar.blockedRunning');
    return null;
  }

  function cueText(step: StepState): string | null {
    if (step.id !== current.id) return null;
    if (step.status === 'blocked' || step.reason === 'running') return reasonText(step);
    if (step.status === 'done') return t('stepbar.status.done');
    return t('stepbar.status.current');
  }

  function nextAction(kind: NextKind): { label: string; act: () => void } | null {
    if (kind === 'none') return null;
    if (kind === 'open-workspace') return { label: t('stepbar.next.openWorkspace'), act: onOpenWorkspace };
    if (kind === 'new-case') return { label: t('stepbar.next.create'), act: onNewCase };
    if (kind === 'create-fluid') return { label: t('stepbar.next.createFluid'), act: () => { createFluidAction?.(); } };
    if (kind === 'edit') {
      const edit = SIMULATION_STEPS.find((step) => step.id === 'edit');
      return { label: t('stepbar.next.edit'), act: () => onDraftQuestion(t(edit?.promptKey ?? 'sim.step.edit.prompt')) };
    }
    if (kind === 'validate') return { label: t('stepbar.next.validate'), act: () => onRunCommand('validate') };
    if (kind === 'preview-run') return { label: t('stepbar.next.run'), act: () => onRunCommand('preview-run') };
    if (kind === 'open-run') return { label: t('stepbar.next.openRun'), act: () => onRunCommand('open-run') };
    return { label: t('stepbar.next.results'), act: () => onSelectView('results') };
  }

  // Results already open and analysed: "Open results" would be a no-op, so
  // deriveNextAction offers the edit loop instead (existing next.edit copy).
  const onResults = activeView === 'results';
  const decision = deriveNextAction({
    states,
    canCreateFluid,
    activeView: onResults ? 'results' : (activeView ?? null),
  });
  const next = nextAction(decision.kind);
  const shortName = (id: StepState['id']): string => t(`stepbar.short.${id}`);

  return (
    <section ref={barRef} className="step-bar" data-stepbar aria-label={t('sim.stepsAria')}>
      <div className="step-bar-main">
        <ol className="step-bar-steps" data-stepbar-steps>
          {states.map((step, index) => {
            const highlighted = step.id === current.id;
            const open = step.id === openStep;
            const reason = step.status === 'blocked' ? reasonText(step) : null;
            const cue = cueText(step);
            const statusText = reason
              ? t('stepbar.status.blocked', { reason })
              : t(`stepbar.status.${step.status}`);
            return (
              <li key={step.id} className={`step-cell is-${step.status}${highlighted ? ' is-highlighted' : ''}`} aria-current={highlighted ? 'step' : undefined}>
                {index > 0 && <i className="pixel-sep step-gap" aria-hidden="true" />}
                <button
                  type="button"
                  ref={(node) => { if (node) stepRefs.current.set(step.id, node); else stepRefs.current.delete(step.id); }}
                  className="step-open"
                  title={reason ?? shortName(step.id)}
                  aria-label={`${shortName(step.id)}, ${statusText}`}
                  aria-expanded={open}
                  onClick={(event) => {
                    if (open) closePopover(false);
                    else openPopover(step.id, event.currentTarget);
                  }}
                >
                  <span className="step-num" aria-hidden="true">{step.status === 'done' ? <Icon name="ok" size={12} /> : index + 1}</span>
                  <span className="step-name">{shortName(step.id)}</span>
                  {cue !== null && (
                    <span className={step.status === 'blocked' || step.reason === 'running' ? 'step-reason' : 'step-here'}>{cue}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
        {next === null ? null : (
          <Button variant="primary" className="step-next" onClick={next.act}>
            {t('stepbar.nextLabel', { action: next.label })}
          </Button>
        )}
      </div>
      <p className="stepbar-counter" aria-hidden="true">{t('stepbar.position', { n: currentIndex + 1, step: shortName(current.id) })}</p>
      {openStep !== null && (
        <div
          id={STEPBAR_DETAIL_ID}
          className="stepbar-detail"
          data-stepbar-popover
          role="dialog"
          aria-label={t('stepbar.detail')}
          tabIndex={-1}
          ref={(node) => {
            popRef.current = node;
            node?.focus({ preventScroll: true });
          }}
          style={{ left: anchorLeft }}
        >
          <SimulationGuideBody
            activeCaseName={activeCaseName} busy={chat.busy}
            healthReady={online} providerReady={providerReady} hasDraft={hasDraft}
            newCaseStarter={newCaseStarter} intakeEvidence={intakeEvidence}
            onDraft={onDraftQuestion} onOpenWorkspace={onOpenWorkspace} onOpenSettings={onOpenSettings}
            createFluidAction={createFluidAction}
            selectedStep={openStep}
            nativeTab={nativeTab}
          />
          <div className="stepbar-detail-nav">
            <button
              type="button" className="stepbar-detail-navbtn"
              disabled={stepIndex(openStep) === 0}
              onClick={() => stepTo(states[stepIndex(openStep) - 1].id)}
            >{t('stepbar.prevStep')}</button>
            <button
              type="button" className="stepbar-detail-navbtn"
              disabled={stepIndex(openStep) === states.length - 1}
              onClick={() => stepTo(states[stepIndex(openStep) + 1].id)}
            >{t('stepbar.nextStep')}</button>
          </div>
        </div>
      )}
    </section>
  );
}
