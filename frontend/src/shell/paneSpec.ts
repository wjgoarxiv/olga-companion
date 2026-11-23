import { readLocalStorage, writeLocalStorage } from '../safeLocalStorage.ts';

// M2 pane mechanics: one exported spec object (defaults, clamps, storage
// keys) shared by the dock/explorer/panel handles, plus the load-time
// viewport re-clamp. Centre floor 320px is enforced against the stored
// widths only; open/closed state and foreign keys are never touched, and
// the floor never strands an approval card (dock minimum keeps it usable,
// and with approvalOpen the debit is skipped entirely).
export const PANE_SPEC = {
  dock: {
    defaultWidth: 384,
    minWidth: 300,
    maxWidth: 560,
    storageKey: 'olga-companion.dock.width',
  },
  explorer: {
    defaultWidth: 248,
    minWidth: 200,
    maxWidth: 480,
    storageKey: 'olga-companion.explorer.width',
  },
  panel: {
    defaultHeight: 168,
    minHeight: 120,
    maxHeight: 480,
    storageKey: 'olga-companion.panel.height',
  },
  centreFloor: 320,
} as const;

export type PaneStore = {
  readonly getItem: (key: string) => string | null;
  readonly setItem: (key: string, value: string) => void;
};

const browserStore: PaneStore = {
  getItem: (key) => readLocalStorage(key),
  setItem: (key, value) => { writeLocalStorage(key, value); },
};

/**
 * Explicit user-resize marker. The mount effect persists the current width
 * even when the user never touched the handle, so a stored width alone
 * cannot tell "fresh profile" from "user resized" — only drag, keyboard
 * and double-click set this marker.
 */
export function userResizeKey(storageKey: string): string {
  return `${storageKey}.touched`;
}

export function markUserResize(storageKey: string, store: PaneStore = browserStore): void {
  store.setItem(userResizeKey(storageKey), '1');
}

export function hasUserResize(storageKey: string, store: PaneStore = browserStore): boolean {
  return store.getItem(userResizeKey(storageKey)) === '1';
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

function readStoredWidth(store: PaneStore, storageKey: string): number | null {
  const stored = Number(store.getItem(storageKey));
  return Number.isFinite(stored) && stored > 0 ? stored : null;
}

/**
 * Re-clamp persisted pane widths against the current viewport so the
 * centre keeps at least `centreFloor` px. Overflow is debited from the
 * dock first (last-writer-wins), then the explorer; no pane drops below
 * its minimum and open/closed flags are never written. With
 * `approvalOpen` the centre-floor debit is skipped so the approval card
 * keeps whatever dock width it needs (plain [min,max] clamping still
 * applies). Idempotent: call at handle mount (which is load for these
 * components) before reading the stored value.
 */
export function reclampPersistedWidths(
  viewportWidth: number,
  store: PaneStore = browserStore,
  opts: { readonly approvalOpen?: boolean } = {},
): { readonly dock: number; readonly explorer: number } {
  const dockSpec = PANE_SPEC.dock;
  const explorerSpec = PANE_SPEC.explorer;
  let dock = readStoredWidth(store, dockSpec.storageKey) ?? dockSpec.defaultWidth;
  let explorer = readStoredWidth(store, explorerSpec.storageKey) ?? explorerSpec.defaultWidth;
  dock = clampNumber(dock, dockSpec.minWidth, dockSpec.maxWidth);
  explorer = clampNumber(explorer, explorerSpec.minWidth, explorerSpec.maxWidth);
  if (!opts.approvalOpen) {
    const budget = viewportWidth - PANE_SPEC.centreFloor;
    let overflow = dock + explorer - budget;
    if (overflow > 0) {
      const dockCut = Math.min(overflow, dock - dockSpec.minWidth);
      dock -= dockCut;
      overflow -= dockCut;
    }
    if (overflow > 0) {
      const explorerCut = Math.min(overflow, explorer - explorerSpec.minWidth);
      explorer -= explorerCut;
      overflow -= explorerCut;
    }
  }
  const prevDock = readStoredWidth(store, dockSpec.storageKey);
  const prevExplorer = readStoredWidth(store, explorerSpec.storageKey);
  if (prevDock !== null && prevDock !== dock) store.setItem(dockSpec.storageKey, String(dock));
  if (prevExplorer !== null && prevExplorer !== explorer) store.setItem(explorerSpec.storageKey, String(explorer));
  return { dock, explorer };
}
