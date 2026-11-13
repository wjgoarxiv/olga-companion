import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import StepBar, { type StepChat, type StepCommand } from './StepBar';
import FluidTableFlow, {
  getFluidTableFlowRequests,
  stageTabPreview,
  subscribeFluidTableFlow,
} from './FluidTableFlow';
import { SHELL_COMMANDS } from './commands';
import { activeCaseStepFacts, useStepStates } from './useStepState';
import { directRunInFlight, getDirectRuns, getDirectValidations, recordDirectRun, subscribeDirectValidations } from './directValidation';
import { subscribeRunObservations } from '../taskbarRunFeed.mjs';
import { requestTabPreview } from './workspaceEvents';
import { useLocale } from '../i18n/index.ts';
import { Button } from '../ui/Button';
import type { WorkspaceContext } from '../workspaceApi';
import type { WorkbenchView } from './useWorkbenchLayout';

export const NEW_CASE_STARTER = 'OLGA 초보자입니다. 새 케이스를 처음부터 만들고 싶습니다. 필요한 값을 하나씩 물어봐 주세요.';

export interface StepBarSlotProps {
  readonly workspace: WorkspaceContext;
  readonly chat: StepChat;
  readonly online: boolean;
  readonly providerReady: boolean;
  readonly preferredResultId: string | null;
  readonly onSelectView: (next: WorkbenchView) => void;
  readonly onRunCommand: (id: StepCommand | 'create-fluid-table') => void;
  readonly onOpenDock: () => void;
  readonly nativeTab?: boolean;
  readonly activeView?: WorkbenchView;
}

function baseName(path: string): string {
  const slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return slash < 0 ? path : path.slice(slash + 1);
}

/** App placement for the M0 step bar: owns the starter-text fallback and the
    draft-then-open-dock wiring so App.tsx keeps one slot tag. No behavior of
    its own — every action routes through the same StepBar props as before.
    W3-L3 also hosts the M4 no-tab banner here: the slot already holds the
    workspace list, the chat timeline (for the pvt_reference degrade check)
    and the openers, which the frozen CentreViews props cannot provide. */
export default function StepBarSlot(props: StepBarSlotProps) {
  const { t } = useLocale();
  const starter = t('app.newCaseStarter') ?? NEW_CASE_STARTER;
  const tabCases = props.workspace.cases.filter((entry) => entry.suffix === '.tab');
  // Installing an example switches the case without clearing the shown result, so it counts only for its own case.
  const activeName = props.workspace.active.name ?? null;
  const resultOwner = useRef<{ readonly id: string | null; readonly caseName: string | null }>({ id: null, caseName: null });
  if (resultOwner.current.id !== props.preferredResultId) resultOwner.current = { id: props.preferredResultId, caseName: activeName };
  const scopedResultId = resultOwner.current.caseName === activeName ? props.preferredResultId : null;
  const directValidations = useSyncExternalStore(subscribeDirectValidations, getDirectValidations, getDirectValidations);
  useSyncExternalStore(subscribeDirectValidations, getDirectRuns, getDirectRuns);
  useEffect(() => subscribeRunObservations((observation) => {
    if (observation.kind === 'run') recordDirectRun(observation.status as Parameters<typeof recordDirectRun>[0]);
  }), []);
  const facts = activeCaseStepFacts({
    activeCaseName: props.workspace.active.name,
    cases: props.workspace.cases,
    timeline: props.chat.timeline,
    directValidations,
  });
  const states = useStepStates({
    activeCaseName: props.workspace.active.name,
    tabCount: facts.tabCount,
    hasRunOutputs: facts.hasRunOutputs,
    hasEvidence: facts.hasEvidence,
    timeline: props.chat.timeline,
    preferredResultId: scopedResultId,
    hasWorkspace: props.workspace.root.trim() !== '',
    directRunInFlight: props.workspace.active.name ? directRunInFlight(props.workspace.active.name) : false,
  });
  const current = states.find((step) => step.status === 'current' || step.status === 'blocked')
    ?? states[states.length - 1];
  const evidence = facts.evidence;
  const pvtRef = typeof evidence?.pvt_reference === 'string' ? evidence.pvt_reference : '';
  const pvtUnresolvable = pvtRef !== ''
    && !props.workspace.cases.some((entry) => entry.name === pvtRef || entry.rel === pvtRef || baseName(entry.rel) === baseName(pvtRef));
  const showBanner = (current.id === 'create' || current.id === 'validate')
    && (tabCases.length === 0 || pvtUnresolvable);
  // Degrade path: without the registered T5 entry the primary action hides
  // and the banner offers only the two non-create buttons — never a dead one.
  const canCreateFluid = SHELL_COMMANDS.some((command) => command.id === 'create-fluid-table');
  const firstTab = tabCases[0] ?? null;

  const [flowOpen, setFlowOpen] = useState(false);
  const flowSignal = useSyncExternalStore(subscribeFluidTableFlow, getFluidTableFlowRequests);
  useEffect(() => {
    if (flowSignal > 0) setFlowOpen(true);
  }, [flowSignal]);
  // Focus return: the dialog takes focus on open; closing hands it back to
  // the banner entry that opened it. No Esc/click-outside (form protection).
  const createBtnRef = useRef<HTMLButtonElement | null>(null);
  const bannerTriggerRef = useRef(false);
  useEffect(() => {
    if (!flowOpen && bannerTriggerRef.current) {
      bannerTriggerRef.current = false;
      createBtnRef.current?.focus({ preventScroll: true });
    }
  }, [flowOpen]);

  function openPreview() {
    props.onSelectView('workspace');
    if (firstTab === null) return;
    stageTabPreview(firstTab.rel);
    window.dispatchEvent(requestTabPreview(firstTab.rel));
  }

  return (
    <>
      <StepBar
        workspace={props.workspace}
        chat={props.chat}
        online={props.online}
        providerReady={props.providerReady}
        newCaseStarter={starter}
        states={states}
        tabCount={facts.tabCount}
        intakeEvidence={facts.evidence}
        onDraftQuestion={(prompt) => { props.chat.setInput(prompt); props.onOpenDock(); }}
        onNewCase={() => { props.chat.setInput(starter); props.onOpenDock(); }}
        onSelectView={props.onSelectView}
        onRunCommand={props.onRunCommand}
        onOpenWorkspace={() => props.onSelectView('workspace')}
        onOpenSettings={() => props.onSelectView('settings')}
        nativeTab={props.nativeTab}
        activeView={props.activeView}
      />
      {showBanner && (
        <section className="fluid-banner" data-fluid-banner aria-label={t('tabbanner.need')}>
          <div className="fluid-banner-copy">
            <h2>{t('tabbanner.need')}</h2>
            <p>{t('tabbanner.how')}</p>
          </div>
          <div className="fluid-banner-actions">
            {canCreateFluid && (
              <Button
                variant="primary" ref={createBtnRef}
                onClick={() => { bannerTriggerRef.current = true; props.onRunCommand('create-fluid-table'); }}
              >{t('tabbanner.create')}</Button>
            )}
            <Button variant="secondary" onClick={() => props.onSelectView('workspace')}>{t('tabbanner.openWorkspace')}</Button>
            <Button
              variant="secondary" onClick={openPreview}
              disabled={firstTab === null} title={t('tabbanner.previewHint')}
            >{t('tabbanner.preview')}</Button>
          </div>
        </section>
      )}
      {flowOpen && (
        <FluidTableFlow
          chat={props.chat}
          activeCaseName={props.workspace.active.name}
          onOpenDock={props.onOpenDock}
          onClose={() => setFlowOpen(false)}
          nativeTab={props.nativeTab}
        />
      )}
    </>
  );
}
