import type { ReactElement } from 'react';
import ToastQueue from './ui/Toast';
import { useAwayNotifications } from './useAwayNotify';
import { useBootGate, type BootRuntime } from './useBootGate';
import { useShutdownGate } from './useShutdownGate';
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
}: {
  runtime: BootRuntime;
  timeline: readonly TimelineItem[];
  busy: boolean;
  hasPendingApproval: boolean;
  workspaceRoot: string;
  selectView: (view: WorkbenchView) => void;
  setDockOpen: (open: boolean) => void;
}): ReactElement {
  const bootOverlay = useBootGate(runtime);
  const shutdownOverlay = useShutdownGate(workspaceRoot);
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
      <ToastQueue />
    </>
  );
}
