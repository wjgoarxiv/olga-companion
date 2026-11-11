import WorkspaceView from '../WorkspaceView';
import ResultsView from '../ResultsView';
import RunView from '../RunView';
import SettingsView from '../SettingsView';
import type { NativeSelectedContext } from '../session';
import type { WorkspaceCase } from '../session';
import type { ProviderInfo } from '../types';
import { Tabs } from '../ui/Tabs';
import { PixelIcon } from '../ui/PixelIcon';
import { PaneDecor } from '../ui/PaneDecor';
import { useLocale } from '../i18n/index.ts';
import type { WorkbenchView } from './useWorkbenchLayout';

const TAB_ORDER: readonly WorkbenchView[] = ['workspace', 'results', 'run', 'settings'];

function tabLabel(view: WorkbenchView, t: (key: 'nav.workspace' | 'nav.results' | 'nav.run' | 'nav.settings') => string | undefined): string {
  return t(`nav.${view}`) ?? view;
}

export default function CentreViews({
  tabs,
  view,
  onSelect,
  workspaceCases,
  workspaceRoot,
  activeCaseName,
  contextKey,
  onOpenSettings,
  onDraftQuestion,
  onNewCase,
  preferredResultId,
  onPreferredResultConsumed,
  onOpenRun,
  onOpenResult,
  onRunCompleted,
  onOpenWorkspace,
  providers,
  provider,
  model,
  effort,
  onProvider,
  onModel,
  onEffort,
  contextGeneration,
  onContextSelected,
}: {
  readonly tabs: readonly WorkbenchView[];
  readonly view: WorkbenchView;
  readonly onSelect: (next: WorkbenchView) => void;
  readonly workspaceCases: WorkspaceCase[];
  readonly workspaceRoot: string;
  readonly activeCaseName: string | null;
  readonly contextKey: string;
  readonly onOpenSettings: () => void;
  readonly onDraftQuestion: (prompt: string) => void;
  readonly onNewCase: () => void;
  readonly preferredResultId: string | null;
  readonly onPreferredResultConsumed: () => void;
  readonly onOpenRun: () => void;
  readonly onOpenResult: (resultId: string) => void;
  readonly onRunCompleted: (runId: string) => void;
  readonly onOpenWorkspace: () => void;
  readonly providers: ProviderInfo[];
  readonly provider: string;
  readonly model: string;
  readonly effort: string;
  readonly onProvider: (p: string) => void;
  readonly onModel: (m: string) => void;
  readonly onEffort: (e: string) => void;
  readonly contextGeneration: number;
  readonly onContextSelected: (context: NativeSelectedContext) => void | Promise<void>;
}) {
  const { t } = useLocale();
  const items = TAB_ORDER.filter((tab) => tabs.includes(tab))
    .map((id) => ({ id, label: tabLabel(id, t) }));
  return (
    <div className="wb-centre-tabs" data-coord="B1">
      <PaneDecor />
      <span className="wb-pane-idx wb-centre-idx" aria-hidden="true">02</span>
      <PixelIcon name="bar" size={12} className="pixel-sep pane-head-sep" />
      <Tabs items={items} value={view} onChange={(next) => {
        if (next === 'workspace' || next === 'results' || next === 'run' || next === 'settings') onSelect(next);
      }} ariaLabel={t('shell.tabsLabel')}>
        {view === 'workspace' && (
          <WorkspaceView key={contextKey}
            cases={workspaceCases}
            root={workspaceRoot}
            activeCase={activeCaseName}
            onOpenSettings={onOpenSettings}
            onNewCase={onNewCase}
          />
        )}
        {view === 'results' && <ResultsView key={contextKey} root={workspaceRoot} activeCaseName={activeCaseName} preferredResultId={preferredResultId} onPreferredResultConsumed={onPreferredResultConsumed} onOpenRun={onOpenRun} workspaceCases={workspaceCases} />}
        {view === 'run' && <RunView key={contextKey} onOpenWorkspace={onOpenWorkspace} onOpenResult={onOpenResult} onRunCompleted={onRunCompleted} onDraftQuestion={onDraftQuestion} />}
        {view === 'settings' && (
          <SettingsView key={contextKey}
            providers={providers} provider={provider} model={model} effort={effort}
            onProvider={onProvider} onModel={onModel} onEffort={onEffort}
            workspaceRoot={workspaceRoot} contextGeneration={contextGeneration} onContextSelected={onContextSelected}
          />
        )}
      </Tabs>
    </div>
  );
}
