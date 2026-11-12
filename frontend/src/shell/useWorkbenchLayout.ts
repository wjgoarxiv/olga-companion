import { useCallback, useRef, useState } from 'react';
import { readLocalStorage, writeLocalStorage } from '../safeLocalStorage';
import { playCue } from '../sound.mjs';

export type WorkbenchView = 'workspace' | 'results' | 'run' | 'settings';
export type BottomPanelTab = 'problems' | 'console' | 'outputs';

export interface WorkbenchLayout {
  readonly view: WorkbenchView;
  readonly tabs: readonly WorkbenchView[];
  readonly dockOpen: boolean;
  readonly explorerOpen: boolean;
  readonly panelOpen: boolean;
  readonly panelTab: BottomPanelTab;
}

export const WORKBENCH_LAYOUT_KEY = 'olga-companion.workbench-layout.v1';
const LEGACY_VIEW_KEY = 'olga_view';

const VIEWS: readonly WorkbenchView[] = ['workspace', 'results', 'run', 'settings'];
const PANEL_TABS: readonly BottomPanelTab[] = ['problems', 'console', 'outputs'];

const DEFAULT_LAYOUT: WorkbenchLayout = {
  view: 'workspace',
  tabs: ['workspace'],
  dockOpen: true,
  explorerOpen: true,
  panelOpen: true,
  panelTab: 'problems',
};

function isWorkbenchView(value: unknown): value is WorkbenchView {
  return typeof value === 'string' && (VIEWS as readonly string[]).includes(value);
}

function isBottomPanelTab(value: unknown): value is BottomPanelTab {
  return typeof value === 'string' && (PANEL_TABS as readonly string[]).includes(value);
}

function cleanTabs(view: WorkbenchView, tabs: unknown): readonly WorkbenchView[] {
  if (!Array.isArray(tabs)) return [view];
  const kept = tabs.filter(isWorkbenchView).filter((item, index, all) => all.indexOf(item) === index);
  if (!kept.includes(view)) kept.unshift(view);
  return kept.length > 0 ? kept : [view];
}

/** Read the legacy view key once and carry a valid value over. Anything else
    (including the old chat view) falls back to the Explorer. */
function readLegacyView(): WorkbenchView | null {
  const stored = readLocalStorage(LEGACY_VIEW_KEY);
  if (stored === 'workspace' || stored === 'results' || stored === 'run' || stored === 'settings') {
    return stored;
  }
  return null;
}

export function loadWorkbenchLayout(): WorkbenchLayout {
  const raw = readLocalStorage(WORKBENCH_LAYOUT_KEY);
  if (raw !== null && raw !== undefined) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      return DEFAULT_LAYOUT;
    }
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      const view = isWorkbenchView(record['view']) ? record['view'] : DEFAULT_LAYOUT.view;
      const dockOpen = typeof record['dockOpen'] === 'boolean' ? record['dockOpen'] : true;
      const explorerOpen = typeof record['explorerOpen'] === 'boolean' ? record['explorerOpen'] : true;
      const panelOpen = typeof record['panelOpen'] === 'boolean' ? record['panelOpen'] : true;
      const panelTab = isBottomPanelTab(record['panelTab']) ? record['panelTab'] : DEFAULT_LAYOUT.panelTab;
      const tabs = cleanTabs(view, record['tabs']);
      return { view, tabs, dockOpen, explorerOpen, panelOpen, panelTab };
    }
  }
  const carried = readLegacyView();
  if (carried !== null) return { ...DEFAULT_LAYOUT, view: carried, tabs: [carried] };
  return DEFAULT_LAYOUT;
}

export function saveWorkbenchLayout(layout: WorkbenchLayout): void {
  writeLocalStorage(WORKBENCH_LAYOUT_KEY, JSON.stringify(layout));
}

export function useWorkbenchLayout(): {
  readonly layout: WorkbenchLayout;
  readonly selectView: (next: WorkbenchView) => void;
  readonly closeTab: (view: WorkbenchView) => void;
  readonly setDockOpen: (open: boolean) => void;
  readonly setExplorerOpen: (open: boolean) => void;
  readonly setPanelOpen: (open: boolean) => void;
  readonly setPanelTab: (tab: BottomPanelTab) => void;
} {
  const [layout, setLayout] = useState<WorkbenchLayout>(loadWorkbenchLayout);
  const viewRef = useRef(layout.view);
  viewRef.current = layout.view;

  const update = useCallback((getNext: (current: WorkbenchLayout) => WorkbenchLayout) => {
    setLayout((current) => {
      const next = getNext(current);
      saveWorkbenchLayout(next);
      return next;
    });
  }, []);

  const selectView = useCallback((next: WorkbenchView) => {
    if (next !== viewRef.current) playCue('tick');
    update((current) => {
      const tabs = current.tabs.includes(next) ? current.tabs : [...current.tabs, next];
      return { ...current, view: next, tabs };
    });
  }, [update]);

  const closeTab = useCallback((view: WorkbenchView) => {
    update((current) => {
      const tabs = current.tabs.filter((tab) => tab !== view);
      const kept = tabs.length > 0 ? tabs : [current.view];
      const nextView = kept.includes(current.view) ? current.view : kept[kept.length - 1];
      return { ...current, tabs: kept, view: nextView };
    });
  }, [update]);

  const setDockOpen = useCallback((open: boolean) => {
    update((current) => ({ ...current, dockOpen: open }));
  }, [update]);

  const setExplorerOpen = useCallback((open: boolean) => {
    update((current) => ({ ...current, explorerOpen: open }));
  }, [update]);

  const setPanelOpen = useCallback((open: boolean) => {
    update((current) => ({ ...current, panelOpen: open }));
  }, [update]);

  const setPanelTab = useCallback((tab: BottomPanelTab) => {
    update((current) => ({ ...current, panelTab: tab, panelOpen: true }));
  }, [update]);

  return { layout, selectView, closeTab, setDockOpen, setExplorerOpen, setPanelOpen, setPanelTab };
}
