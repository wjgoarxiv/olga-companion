import { useEffect, type ReactElement } from 'react';
import { ExampleGalleryDialog } from './ExampleGallery';
import { EXAMPLE_INSTALLED_EVENT, setExampleWorkspaceRoot } from './examplesApi';
import ToastQueue from './ui/Toast';
import { useAwayNotifications } from './useAwayNotify';
import { useBootGate, type BootRuntime } from './useBootGate';
import { useShutdownGate } from './useShutdownGate';
import { useTaskbarProgress } from './useTaskbarProgress';
import { rememberSettingsSection } from './SettingsView';
import type { TimelineItem } from './timeline';
import type { WorkbenchView } from './shell/useWorkbenchLayout';

/** Boot, shutdown and away-notification wiring, kept out of App so the app
 *  orchestrator stays a thin workbench shell. */
export default function AppLifecycleLayer({
  runtime,
  timeline,
  busy,
  hasPendingApproval,
  workspaceRoot,
  selectView,
  setDockOpen,
  refreshWorkspace,
}: {
  runtime: BootRuntime;
  timeline: readonly TimelineItem[];
  busy: boolean;
  hasPendingApproval: boolean;
  workspaceRoot: string;
  selectView: (view: WorkbenchView) => void;
  setDockOpen: (open: boolean) => void;
  refreshWorkspace: () => Promise<void>;
}): ReactElement {
  setExampleWorkspaceRoot(workspaceRoot);
  useEffect(() => {
    function onInstalled() {
      void refreshWorkspace();
      selectView('workspace');
    }
    window.addEventListener(EXAMPLE_INSTALLED_EVENT, onInstalled);
    return () => window.removeEventListener(EXAMPLE_INSTALLED_EVENT, onInstalled);
  }, [refreshWorkspace, selectView]);
  const bootOverlay = useBootGate(runtime);
  const shutdownOverlay = useShutdownGate(workspaceRoot);
  useTaskbarProgress(workspaceRoot);
  useAwayNotifications(timeline, busy, hasPendingApproval, {
    onOpenRun: () => { window.focus(); selectView('results'); },
    onOpenApproval: () => { window.focus(); setDockOpen(true); },
    onOpenChat: () => { window.focus(); setDockOpen(true); },
    onOpenUpdates: () => { window.focus(); rememberSettingsSection('updates'); selectView('settings'); },
  });
  return (
    <>
      {bootOverlay}
      {shutdownOverlay}
      <ExampleGalleryDialog />
      <ToastQueue />
    </>
  );
}
