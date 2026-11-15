import { useCallback, useEffect, useMemo } from 'react';
import { matchShellShortcut, type ShellCommandId } from './keymap';
import { SHELL_COMMANDS } from './commands';
import { CREATE_FLUID_TABLE_EVENT } from './useStepState';
import { requestFluidTableFlow } from './FluidTableFlow';
import { requestRunPreview } from '../runPreviewRequest';
import { reviewWorkspaceCase } from '../caseReview';
import { requestExamplesOpen } from '../examplesApi';
import type { WorkspaceCase } from '../workspaceApi';
import { themeRevealAt } from './TitleBar';
import type { TranslateFn, Locale } from '../i18n/index.ts';
import type { WorkbenchLayout } from './useWorkbenchLayout';

/** Read-only derivation: title-bar case actions need an active case.
    Nothing here executes; command bodies are unchanged. W3-L3 builds on
    this hunk for the create-fluid-table registration. */
export function caseActionsEnabled(activeCaseName: string | null): boolean {
  return activeCaseName != null;
}

export function useWorkbenchCommands({
  t,
  locale,
  setLocale,
  layout,
  selectView,
  setDockOpen,
  setPanelOpen,
  setPanelTab,
  setPaletteOpen,
  setShortcutsOpen,
  paletteOpen,
  shortcutsOpen,
  activeCaseName,
  cases,
}: {
  readonly t: TranslateFn;
  readonly locale: Locale;
  readonly setLocale: (next: Locale) => void;
  readonly layout: WorkbenchLayout;
  readonly selectView: (next: 'workspace' | 'results' | 'run' | 'settings') => void;
  readonly setDockOpen: (open: boolean) => void;
  readonly setPanelOpen: (open: boolean) => void;
  readonly setPanelTab: (tab: 'problems' | 'console' | 'outputs') => void;
  readonly setPaletteOpen: React.Dispatch<React.SetStateAction<boolean>>;
  readonly setShortcutsOpen: React.Dispatch<React.SetStateAction<boolean>>;
  readonly paletteOpen: boolean;
  readonly shortcutsOpen: boolean;
  /** Read-only: the active case name when one is selected. Absent until wired. */
  readonly activeCaseName?: string | null;
  readonly cases?: readonly WorkspaceCase[];
}) {
  const runCommand = useCallback((id: ShellCommandId) => {
    if (id === 'go-case') selectView('workspace');
    else if (id === 'go-results') selectView('results');
    else if (id === 'go-runs') selectView('run');
    else if (id === 'go-settings') selectView('settings');
    else if (id === 'toggle-dock') setDockOpen(!layout.dockOpen);
    else if (id === 'toggle-panel') setPanelOpen(!layout.panelOpen);
    else if (id === 'validate') {
      selectView('workspace');
      setPanelOpen(true);
      setPanelTab('problems');
      const active = cases?.find((entry) => entry.name === activeCaseName && entry.suffix === '.genkey');
      if (active && activeCaseName) void reviewWorkspaceCase(active.rel, activeCaseName);
    }
    else if (id === 'open-examples') requestExamplesOpen();
    // Both title-bar/palette Run entries land on Run, then flag a preview for RunView to consume.
    else if (id === 'preview-run' || id === 'open-run') selectView('run'), requestRunPreview();
    else if (id === 'open-palette') setPaletteOpen(true);
    else if (id === 'toggle-theme') themeRevealAt(window.innerWidth - 120, 44);
    else if (id === 'switch-language') setLocale(locale === 'ko' ? 'en' : 'ko');
    else if (id === 'show-shortcuts') setShortcutsOpen(true);
    else if (id === 'show-guide') { setDockOpen(true); window.dispatchEvent(new CustomEvent('olga:open-simulation-guide')); }
    // T5 route only: open the fluid-table flow on the workspace view.
    // Explicit clicks only; save/link travel through the existing draft +
    // approval path inside the flow, never from this handler.
    else if (id === 'create-fluid-table') { selectView('workspace'); requestFluidTableFlow(); }
  }, [activeCaseName, cases, layout.dockOpen, layout.panelOpen, locale, selectView, setDockOpen, setLocale, setPaletteOpen, setPanelOpen, setPanelTab, setShortcutsOpen]);

  // The W2-L1 ①-detail entry dispatches this event; the palette entry and
  // the banner route through runCommand above. One handler serves all three.
  useEffect(() => {
    function onCreateFluidTable() {
      runCommand('create-fluid-table');
    }
    window.addEventListener(CREATE_FLUID_TABLE_EVENT, onCreateFluidTable);
    return () => window.removeEventListener(CREATE_FLUID_TABLE_EVENT, onCreateFluidTable);
  }, [runCommand]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const id = matchShellShortcut({ key: event.key, ctrlKey: event.ctrlKey, metaKey: event.metaKey });
      if (id === null) return;
      if (id === 'open-palette') {
        event.preventDefault();
        setPaletteOpen((wasOpen) => !wasOpen);
        return;
      }
      if (paletteOpen || shortcutsOpen) return;
      event.preventDefault();
      runCommand(id);
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [paletteOpen, runCommand, setPaletteOpen, shortcutsOpen]);

  const paletteItems = useMemo(
    () => SHELL_COMMANDS.map((command) => ({ id: command.id, label: t(command.labelKey) ?? command.id })),
    [t],
  );

  const caseReady = caseActionsEnabled(activeCaseName ?? null);

  return { runCommand, paletteItems, canValidate: caseReady, canPreview: caseReady, canRun: caseReady };
}
