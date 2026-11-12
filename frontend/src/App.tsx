import { useEffect, useRef, useState } from 'react';
import { RuntimeUnavailableView } from './RuntimeUnavailableView';
import { useLocale } from './i18n/index.ts';
import { operatorEffortLabel, operatorModelLabel } from './ProviderPanel';
import * as session from './session';
import { useChatController } from './useChatController';
import { useRuntimeConnection } from './useRuntimeConnection';
import { createRequestEpoch } from './requestEpoch';
import { createLatestAsyncAction } from './latestAsync';
import { OPEN_ARTIFACT_IN_RESULTS_EVENT, parseOpenArtifactEventDetail } from './artifactNavigation';
import { prefetchResultInventory } from './resultInventoryCache';
import { useRunCompletionOpener } from './useRunCompletionOpener';
import { useProviderSelection } from './useProviderSelection';
import { useWorkbenchLayout, type WorkbenchView } from './shell/useWorkbenchLayout';
import { useOverlayPanels } from './shell/useOverlayPanels';
import { useWorkbenchCommands } from './shell/useWorkbenchCommands';
import { type ShellCommandId } from './shell/keymap';
import TitleBar from './shell/TitleBar';
import StepBarSlot, { NEW_CASE_STARTER } from './shell/StepBarSlot';
import ActivityBar from './shell/ActivityBar';
import ExplorerPanel from './shell/ExplorerPanel';
import CentreViews from './shell/CentreViews';
import ChatDockView from './shell/ChatDockView';
import BottomPanel from './shell/BottomPanel';
import StatusBar from './shell/StatusBar';
import ShortcutsDialog from './shell/ShortcutsDialog';
import { CommandPalette } from './ui/CommandPalette';
import './styles.css';

export default function App() {
  const { t, locale, setLocale } = useLocale();
  const {
    provider, setProvider, model, setModel, effort, setEffort, setOnline, applyRuntimeProviders,
  } = useProviderSelection();
  const { layout, selectView: storeView, setDockOpen, setExplorerOpen, setPanelOpen, setPanelTab } = useWorkbenchLayout();
  useOverlayPanels({ dockOpen: layout.dockOpen, explorerOpen: layout.explorerOpen, setDockOpen, setExplorerOpen });
  const view = layout.view;
  const [workspaceContext, setWorkspaceContext] = useState<session.WorkspaceContext>({
    root: '', cases: [], active: { name: null, path: null }, generation: 0,
  });
  const [contextRevision, setContextRevision] = useState(0);
  const workspaceRefreshEpochRef = useRef(createRequestEpoch());
  const activeCaseActionRef = useRef(createLatestAsyncAction());
  const workbenchRef = useRef<HTMLElement>(null);
  const [preferredResultId, setPreferredResultId] = useState<string | null>(null);
  // The step bar's "analysed" mark: the preference above is one-shot, this one lasts until the case changes.
  const [shownResultId, setShownResultId] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const chat = useChatController({ effort, model, provider, refreshWorkspace, t, workspaceGeneration: workspaceContext.generation });
  const runtime = useRuntimeConnection({
    sessionId: chat.sessionId,
    startInitialSession: chat.startInitialSession,
    onProviders: applyRuntimeProviders,
    onWorkspace: applyRuntimeWorkspace,
  });
  const health = runtime.health;
  const providers = runtime.providers;

  function bootstrap() { runtime.bootstrap(); }

  // An approval arriving while the dock is collapsed opens the dock. The
  // freshly mounted ApprovalCard moves focus to its explicit button itself.
  const pendingApprovalId = chat.pendingApproval?.pending_id;
  useEffect(() => {
    if (!pendingApprovalId) return;
    setDockOpen(true);
  }, [pendingApprovalId, setDockOpen]);

  useEffect(() => { void bootstrap(); }, []);

  useEffect(() => {
    setOnline(runtime.state === 'online');
  }, [runtime.state, setOnline]);

  useEffect(() => {
    function handleOpenArtifact(event: Event) {
      if (!(event instanceof CustomEvent)) return;
      try {
        const detail = parseOpenArtifactEventDetail(event.detail);
        openResult(detail.result_id);
      } catch {
        return;
      }
    }
    window.addEventListener(OPEN_ARTIFACT_IN_RESULTS_EVENT, handleOpenArtifact);
    return () => window.removeEventListener(OPEN_ARTIFACT_IN_RESULTS_EVENT, handleOpenArtifact);
  }, []);

  function applyRuntimeWorkspace(next: session.WorkspaceContext) {
    workspaceRefreshEpochRef.current.invalidate();
    activeCaseActionRef.current.invalidate();
    setWorkspaceContext(next);
  }

  async function refreshWorkspace() {
    activeCaseActionRef.current.invalidate();
    const requestId = workspaceRefreshEpochRef.current.begin();
    try {
      const next = await session.fetchWorkspaceContext();
      if (workspaceRefreshEpochRef.current.isCurrent(requestId)) setWorkspaceContext(next);
    } catch {
      return;
    }
  }

  function applyWorkspaceContext(next: session.NativeSelectedContext) {
    workspaceRefreshEpochRef.current.invalidate();
    activeCaseActionRef.current.invalidate();
    chat.invalidateContext();
    setPreferredResultId(null);
    setShownResultId(null);
    setWorkspaceContext({
      root: next.root,
      cases: next.cases,
      active: next.active,
      generation: next.generation,
    });
    setContextRevision((revision) => revision + 1);
  }

  function selectView(next: WorkbenchView) {
    storeView(next);
    requestAnimationFrame(() => workbenchRef.current?.focus());
  }

  function showResult(resultId: string) { setPreferredResultId(resultId); setShownResultId(resultId); }

  function openResult(resultId: string) {
    showResult(resultId);
    selectView('results');
  }

  async function pickCase(rel: string) {
    workspaceRefreshEpochRef.current.invalidate();
    await activeCaseActionRef.current.run(
      () => session.setActiveCase(rel, workspaceContext.generation),
      {
        onSuccess: (active) => {
          setPreferredResultId(null);
          setShownResultId(null);
          setWorkspaceContext((current) => ({ ...current, active }));
          setContextRevision((revision) => revision + 1);
        },
        onError: (error) => {
          chat.reportError(error instanceof Error ? error : new Error(String(error)));
        },
      },
    );
  }

  const workspaceCases = workspaceContext.cases;
  const workspaceRoot = workspaceContext.root;
  const activeCaseName = workspaceContext.active.name;
  const contextKey = `${workspaceContext.generation}:${contextRevision}`;
  const announceRunCompleted = useRunCompletionOpener({ timeline: chat.timeline, sessionId: chat.sessionId ?? null, composerText: chat.input,
    workspaceRoot, activeCaseName, preferResult: showResult, openResultsView: () => selectView('results') });
  useEffect(() => {
    if (runtime.state !== 'online' || !workspaceRoot || !chat.sessionId) return;
    void prefetchResultInventory(workspaceRoot, session.fetchResults).catch(() => undefined);
  }, [runtime.state, workspaceRoot, chat.sessionId]);
  const activeProvider = providers.find((candidate) => candidate.provider === provider);
  const activeKnown = activeProvider?.known ?? Boolean(activeProvider);
  const activeConnected = activeProvider ? (activeProvider.connected ?? activeProvider.has_catalog) : false;
  const statusDisconnected = Boolean(activeProvider) && activeKnown && !activeConnected;
  const activeModel = activeProvider?.models.find((candidate) => candidate.id === model);
  const statusModelLabel = !statusDisconnected && activeModel ? operatorModelLabel(activeModel) : t('status.disconnected');
  const statusModelEffort = !statusDisconnected && activeModel && provider === 'openai' ? operatorEffortLabel(effort) : null;
  const runtimeModelLabel = statusModelEffort ? `${statusModelLabel} · ${statusModelEffort}` : statusModelLabel;

  const { runCommand, paletteItems } = useWorkbenchCommands({
    t, locale, setLocale, layout, selectView, setDockOpen, setPanelOpen, setPanelTab,
    setPaletteOpen, setShortcutsOpen, paletteOpen, shortcutsOpen,
  });

  return (
    <div className="wb">
      <a className="skip-link" href="#primary-workbench">{t('status.skipLink')}</a>
      <TitleBar
        activeCaseName={activeCaseName}
        cases={workspaceCases}
        workspaceRoot={workspaceRoot}
        contextGeneration={workspaceContext.generation}
        onPick={pickCase}
        onContextSelected={applyWorkspaceContext}
        onHome={() => selectView('workspace')}
        onValidate={() => runCommand('validate')}
        onPreviewRun={() => runCommand('preview-run')}
        onOpenRun={() => runCommand('open-run')}
        onOpenPalette={() => setPaletteOpen(true)}
      />
      <StepBarSlot workspace={workspaceContext} chat={chat} online={runtime.state === 'online'} providerReady={Boolean(activeModel)} preferredResultId={shownResultId} onSelectView={selectView} onRunCommand={runCommand} onOpenDock={() => setDockOpen(true)} nativeTab={health?.capabilities.native_tab === true} activeView={view} />
      <p className="wb-narrow-note">{t('shell.narrowNotice')}</p>
      <div className="wb-mid">
        <ActivityBar view={view} onSelect={selectView} explorerOpen={layout.explorerOpen} dockOpen={layout.dockOpen} onToggleExplorer={setExplorerOpen} onToggleDock={setDockOpen} />
        <ExplorerPanel cases={workspaceCases} activeName={activeCaseName} onPick={pickCase} contextGeneration={workspaceContext.generation} onContextSelected={applyWorkspaceContext} open={layout.explorerOpen} onToggle={setExplorerOpen} />
        <main ref={workbenchRef} id="primary-workbench" className="shell-main" tabIndex={-1} aria-label={t('app.workbench', { view })}>
          <h1 className="ui-visually-hidden">{t('app.workbench', { view })}</h1>
          {runtime.state !== 'online' && (
            <RuntimeUnavailableView view={view} state={runtime.state} detail={runtime.operatorMessage} busy={runtime.busy} onRetry={runtime.retry} />
          )}
          {runtime.state === 'online' && (
            <CentreViews
              tabs={layout.tabs}
              view={view}
              onSelect={selectView}
              workspaceCases={workspaceCases}
              workspaceRoot={workspaceRoot}
              activeCaseName={activeCaseName}
              contextKey={contextKey}
              onOpenSettings={() => selectView('settings')}
              onDraftQuestion={(prompt) => { chat.setInput(prompt); setDockOpen(true); }}
              onNewCase={() => { chat.setInput(t('app.newCaseStarter') ?? NEW_CASE_STARTER); setDockOpen(true); }}
              preferredResultId={preferredResultId}
              onPreferredResultConsumed={() => setPreferredResultId(null)}
              onOpenRun={() => selectView('run')}
              onOpenResult={openResult}
              onRunCompleted={announceRunCompleted}
              onOpenWorkspace={() => selectView('workspace')}
              providers={providers}
              provider={provider}
              model={model}
              effort={effort}
              onProvider={setProvider}
              onModel={setModel}
              onEffort={setEffort}
              contextGeneration={workspaceContext.generation}
              onContextSelected={applyWorkspaceContext}
            />
          )}
        </main>
        <ChatDockView
          open={layout.dockOpen}
          onToggle={setDockOpen}
          chat={chat}
          runtimeOnline={runtime.state === 'online'}
          providerReady={Boolean(activeModel)}
          activeCaseName={activeCaseName}
          workspaceGeneration={workspaceContext.generation}
          workspaceCaseCount={workspaceCases.length}
          newCaseStarter={t('app.newCaseStarter') ?? NEW_CASE_STARTER}
          t={t}
          onSelectView={selectView}
        />
        <BottomPanel open={layout.panelOpen} onToggle={setPanelOpen} tab={layout.panelTab} onTab={setPanelTab} onFocusNode={() => selectView('workspace')} />
      </div>
      <StatusBar
        view={view}
        state={runtime.state}
        detail={runtime.operatorMessage}
        busy={runtime.busy}
        retryingLabel={t('runtime.retrying')}
        onRetry={runtime.retry}
        health={health}
        modelLabel={runtimeModelLabel}
        onOpenUpdates={() => selectView('settings')}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        label={t('shell.palette')}
        placeholder={t('shell.palette')}
        items={paletteItems}
        onSelect={(id) => { setPaletteOpen(false); runCommand(id as ShellCommandId); }}
      />
      {shortcutsOpen && <ShortcutsDialog onClose={() => setShortcutsOpen(false)} />}    </div>
  );
}
