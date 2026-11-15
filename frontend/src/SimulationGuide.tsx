import { useEffect, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import NewCaseChecklist from './NewCaseChecklist';
import { SIMULATION_STEPS } from './simulationSteps';
import { STEPBAR_DETAIL_EVENT } from './shell/useStepState';
import { Button } from './ui/Button';

export type SimulationGuideProps = {
  readonly activeCaseName: string | null;
  readonly busy: boolean;
  readonly healthReady: boolean;
  readonly providerReady: boolean;
  readonly hasDraft: boolean;
  readonly compact?: boolean;
  readonly newCaseStarter: string;
  readonly intakeEvidence: Record<string, unknown> | null;
  readonly onDraft: (prompt: string) => void;
  readonly onOpenWorkspace: () => void;
  readonly onOpenSettings: () => void;
  /** T5 fluid-table entry (M0 FIX): rendered in the ① detail only when set.
      The shell passes it exactly when the workspace needs a .tab and the
      `create-fluid-table` command exists — never a dead button. */
  readonly createFluidAction?: () => void;
  /** Controlled step selection: the StepBar popover owns which step shows and
      renders this body directly — no in-body picker or step list, the stepper
      row and the popover footer already navigate. */
  readonly selectedStep?: string;
  readonly nativeTab?: boolean;
};

/** Dock remnant under D1: one link row to the step bar detail. The 5-step
    list, picker and detail live in the StepBar detail region (GuideBody);
    nothing is duplicated. Activating the link opens the detail and moves
    no composer value, drafts nothing, mints no token. */
export default function SimulationGuide(_props: SimulationGuideProps) {
  // Link mode ignores the guide body props: the dock keeps one row under D1
  // and the full body renders in the StepBar detail region instead.
  void _props;
  const { t } = useLocale();
  useEffect(() => {
    function reopen() { window.dispatchEvent(new CustomEvent(STEPBAR_DETAIL_EVENT)); }
    window.addEventListener('olga:open-simulation-guide', reopen);
    return () => window.removeEventListener('olga:open-simulation-guide', reopen);
  }, []);
  return (
    <a
      className="simulation-guide-link"
      href="#stepbar-detail"
      title={t('stepbar.guideLink')}
      onClick={() => { window.dispatchEvent(new CustomEvent(STEPBAR_DETAIL_EVENT)); }}
    >
      {t('stepbar.guideLink')}
    </a>
  );
}

export function SimulationGuideBody(props: SimulationGuideProps) {
  const { locale, t } = useLocale();
  const [showIntake, setShowIntake] = useState(false);
  const step = SIMULATION_STEPS.find((candidate) => candidate.id === props.selectedStep) ?? SIMULATION_STEPS[0];
  const needsCase = step.requiresCase && !props.activeCaseName;
  const blocked = !props.healthReady || props.busy;

  return (
    <div className="simulation-guide-body" lang={locale}>
      <h2 className="simulation-guide-heading">{t('sim.title')}<span>{t('sim.subtitle')}</span></h2>
      <section className="simulation-guide-detail" aria-label={t('sim.detailAria')} aria-live="polite">
          <h3>{t(step.titleKey)}</h3>
          <p>{t(step.descriptionKey)}</p>
          {!props.healthReady ? (
            <p role="status">{t('sim.guideHealthNote') ?? '앱의 실행 서비스에 연결한 뒤 질문을 준비할 수 있습니다. 상단의 연결 상태에서 다시 시도하세요.'}</p>
          ) : !props.providerReady ? (
            <div className="simulation-guide-action">
              <p>{t('sim.guideProviderNote') ?? '질문을 보내려면 AI 연결이 필요합니다. 설정에서 공급자와 모델을 선택하세요.'}</p>
              <Button onClick={props.onOpenSettings} disabled={props.busy}>{t('sim.guideProviderButton') ?? 'AI 연결 설정'}</Button>
            </div>
          ) : needsCase ? (
            <div className="simulation-guide-action">
              <p>{t('sim.guideCaseNote') ?? '먼저 Workspace에서 사례를 선택하세요. 사례가 없다면 첫 단계에서 새로 만들 수 있습니다.'}</p>
              <Button onClick={props.onOpenWorkspace} disabled={props.busy}>{t('sim.guideCaseButton') ?? '사례 열기'}</Button>
            </div>
          ) : (
            <div className="simulation-guide-action">
              <Button variant="primary" onClick={() => props.onDraft(t(step.promptKey))} disabled={blocked || props.hasDraft}>{t('sim.guideDraftButton') ?? '질문 입력하기'}</Button>
              <p>{props.busy
                ? t('sim.guideBusyNote') ?? '현재 응답이 끝나면 질문을 준비할 수 있습니다.'
                : props.hasDraft
                  ? t('sim.guideDraftNote') ?? '입력창에서 질문을 검토하세요. 다른 질문을 준비하려면 비우기를 누르세요.'
                  : t('sim.guideReadyNote') ?? '입력창에서 내용을 확인한 뒤 전송하세요. 실행 승인은 별도로 받습니다.'}</p>
            </div>
          )}
          {step.id === 'create' && props.createFluidAction && (
            <div className="simulation-guide-action">
              <Button variant="primary" onClick={props.createFluidAction}>{t('stepbar.next.createFluid')}</Button>
            </div>
          )}
          {step.id === 'create' && (
            <div className="simulation-guide-action">
              <Button variant="secondary" onClick={() => { props.onDraft(props.newCaseStarter); setShowIntake(true); }} disabled={blocked || props.hasDraft}>{t('sim.guideCreateButton') ?? '새 케이스 만들기'}</Button>
              <p>{t('sim.guideCreateNote') ?? '준비 목록을 열고 입력창에 시작 문장을 넣습니다. 전송하지 않습니다.'}</p>
            </div>
          )}
          {step.id === 'create' && showIntake && (
            <NewCaseChecklist evidence={props.intakeEvidence} onOpenSettings={props.onOpenSettings} onOpenWorkspace={props.onOpenWorkspace} nativeTab={props.nativeTab} />
          )}
          <dl><dt>{t('sim.checkTitle')}</dt><dd>{t(step.checkKey)}</dd></dl>
      </section>
      <p className="simulation-guide-note">{t('sim.note')}</p>
    </div>
  );
}
