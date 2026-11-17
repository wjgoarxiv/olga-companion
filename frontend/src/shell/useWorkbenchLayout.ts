import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readLocalStorage, writeLocalStorage } from '../safeLocalStorage.ts';
import { playCue } from '../sound.mjs';
import { OVERLAY_BAND_QUERY, inOverlayBandNow, resolveOverlayExclusive } from './overlayExclusive.mjs';

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

export function exclusiveFor(layout: WorkbenchLayout, changed: 'dock' | 'explorer' | null, inBand: boolean): WorkbenchLayout {
  const open = resolveOverlayExclusive(layout, changed, inBand);
  return open.dockOpen === layout.dockOpen && open.explorerOpen === layout.explorerOpen ? layout : { ...layout, ...open };
}

interface OverlayOpen {
  readonly dockOpen: boolean;
  readonly explorerOpen: boolean;
}

/** `intent` is what the user chose and what is persisted. `band` is the one-drawer
 *  view the user shaped while inside the overlay band; it is memory only and is
 *  dropped when the window leaves the band. */
export interface LayoutState {
  readonly intent: WorkbenchLayout;
  readonly band: OverlayOpen | null;
}

/** The drawers that are actually open now. Outside the band that is the intent;
 *  inside it, one drawer: the user's band choice, else the dock (approval card). */
export function effectiveOverlay(state: LayoutState, inBand: boolean): OverlayOpen {
  if (!inBand) return { dockOpen: state.intent.dockOpen, explorerOpen: state.intent.explorerOpen };
  if (state.band) return state.band;
  const shown = exclusiveFor(state.intent, null, true);
  return { dockOpen: shown.dockOpen, explorerOpen: shown.explorerOpen };
}

/** The user opens or closes one drawer. The choice becomes the intent for that
 *  drawer only; in the band the other drawer is hidden in the view, not forgotten. */
export function chooseOverlay(state: LayoutState, changed: 'dock' | 'explorer', open: boolean, inBand: boolean): LayoutState {
  const key = changed === 'dock' ? 'dockOpen' : 'explorerOpen';
  const shown = exclusiveFor({ ...state.intent, ...effectiveOverlay(state, inBand), [key]: open }, changed, inBand);
  return {
    intent: { ...state.intent, [key]: open },
    band: inBand ? { dockOpen: shown.dockOpen, explorerOpen: shown.explorerOpen } : null,
  };
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
  const [state, setState] = useState<LayoutState>(() => ({ intent: loadWorkbenchLayout(), band: null }));
  const [inBand, setInBand] = useState(inOverlayBandNow);
  const viewRef = useRef(state.intent.view);
  viewRef.current = state.intent.view;
  const open = effectiveOverlay(state, inBand);
  const layout = useMemo<WorkbenchLayout>(
    () => ({ ...state.intent, dockOpen: open.dockOpen, explorerOpen: open.explorerOpen }),
    [state.intent, open.dockOpen, open.explorerOpen],
  );

  const update = useCallback((getNext: (current: WorkbenchLayout) => WorkbenchLayout) => {
    setState((current) => {
      const next = getNext(current.intent);
      saveWorkbenchLayout(next);
      return { ...current, intent: next };
    });
  }, []);

  const choose = useCallback((changed: 'dock' | 'explorer', isOpen: boolean) => {
    setState((current) => {
      const next = chooseOverlay(current, changed, isOpen, inOverlayBandNow());
      saveWorkbenchLayout(next.intent);
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

  const setDockOpen = useCallback((isOpen: boolean) => choose('dock', isOpen), [choose]);

  const setExplorerOpen = useCallback((isOpen: boolean) => choose('explorer', isOpen), [choose]);

  // Crossing the band edge re-derives which drawers show; the stored intent is
  // untouched, and a band-only view is dropped so widening restores the intent.
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(OVERLAY_BAND_QUERY);
    const onChange = () => {
      setInBand(query.matches);
      setState((current) => (current.band ? { ...current, band: null } : current));
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const setPanelOpen = useCallback((open: boolean) => {
    update((current) => ({ ...current, panelOpen: open }));
  }, [update]);

  const setPanelTab = useCallback((tab: BottomPanelTab) => {
    update((current) => ({ ...current, panelTab: tab, panelOpen: true }));
  }, [update]);

  return { layout, selectView, closeTab, setDockOpen, setExplorerOpen, setPanelOpen, setPanelTab };
}
