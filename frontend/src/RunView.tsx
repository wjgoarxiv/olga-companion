import { useEffect, useRef, useState } from 'react';
import { RunFailurePanel } from './RunFailurePanel';
import { RunSingleCasePanel } from './RunSingleCasePanel';
import { RunSweepPanel } from './RunSweepPanel';
import { RunViewOverview } from './RunViewOverview';
import { deriveRunViewModel } from './runViewModel';
import { useLocale } from './i18n/index.ts';
import { consumePreviewRequest, usePreviewRequest } from './runPreviewRequest';
import { Segmented } from './ui/Segmented';
import { useRunActions } from './useRunActions';
import { useRunLifecycle } from './useRunLifecycle';
import { useRunViewState } from './useRunViewState';
import { shouldAnnounceRunCompletion } from './runCompletion';

type RunViewProps = {
  readonly onOpenWorkspace: () => void;
  readonly onOpenResult: (resultId: string) => void;
  readonly onRunCompleted?: (runId: string) => void;
  readonly onDraftQuestion?: (prompt: string) => void;
};

type RunMode = 'single' | 'sweep';

export default function RunView({ onOpenWorkspace, onOpenResult, onRunCompleted, onDraftQuestion }: RunViewProps) {
  const [runMode, setRunMode] = useState<RunMode>('single');
  const { t } = useLocale();
  const state = useRunViewState();
  const lifecycle = useRunLifecycle(state);
  const model = deriveRunViewModel(state, t);
  const actions = useRunActions(state, lifecycle, model);
  const { active, activeLoaded, contextUnavailable, error, errorRetriesContext, contextLoading, status, statusSource, supervisionUnknown } = state;
  // The overview already offers this button whenever an error asks for it.
  const retryContext = error && errorRetriesContext ? undefined : lifecycle.retryRunContext;
  const previewRequested = usePreviewRequest();
  const doPreviewRef = useRef(actions.doPreview);
  doPreviewRef.current = actions.doPreview;
  // Title-bar / palette / F5 Preview run and Run land here and request a
  // preview on the active case; consuming runs the existing preview only.
  useEffect(() => {
    if (!previewRequested || !activeLoaded) return;
    consumePreviewRequest();
    void doPreviewRef.current();
  }, [previewRequested, activeLoaded]);
  // A live run reaching its completed terminal state announces once. The shell
  // refreshes Results and opens the output; a restored completed history stays
  // silent, and failed runs never announce.
  const previousRunRef = useRef<{ run_id: string; state: string } | null>(null);
  useEffect(() => {
    const previous = previousRunRef.current;
    const next = status ? { run_id: status.run_id, state: status.state } : null;
    previousRunRef.current = next;
    if (!next || !onRunCompleted || !previous) return;
    const announced = shouldAnnounceRunCompletion(previous, next);
    if (announced) onRunCompleted(announced);
  }, [status, onRunCompleted]);

  return (
    <section className="run-view" aria-label={t('nav.run')}>
      <RunViewOverview
        state={state}
        lifecycle={lifecycle}
        model={model}
        onOpenWorkspace={onOpenWorkspace}
      />
      {!contextUnavailable && active?.path && (
        <div className="run-body">
          <div className="run-mode">
            <Segmented
              ariaLabel={t('run.modeLabel')}
              value={runMode}
              onChange={(next) => setRunMode(next)}
              options={[
                { value: 'single', label: t('run.singleCase') },
                { value: 'sweep', label: t('run.advancedSweep') },
              ]}
            />
          </div>
          <div id="run-mode-panel" className="run-mode-panel" role="group" aria-label={t('run.modeLabel')}>
            {runMode === 'single' ? (
              <RunSingleCasePanel state={state} actions={actions} model={model} />
            ) : (
              <RunSweepPanel state={state} actions={actions} model={model} />
            )}
          </div>
          {runMode === 'single' && status && <RunFailurePanel status={status} historical={statusSource === 'history'} supervisionUnknown={supervisionUnknown} onOpenResult={onOpenResult} onRetryContext={retryContext} onDraftQuestion={onDraftQuestion} contextLoading={contextLoading} />}
        </div>
      )}
    </section>
  );
}
