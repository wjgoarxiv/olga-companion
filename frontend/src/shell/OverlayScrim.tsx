import { useEffect, useRef, useState } from 'react';
import { useLocale } from '../i18n/index.ts';
import { applyInertCover } from './inertCover.mjs';

const OVERLAY_BAND = '(min-width: 769px) and (max-width: 1023px)';
const COVERED_SELECTORS = ['.shell-main', '.wb-panel', '.wb-panel-resizer', '.wb-panel-shut'];
const SHELL_SELECTOR = '.wb-mid';

function focusToggle(which: 'dock' | 'explorer'): void {
  document.getElementById(which === 'dock' ? 'activity-dock-toggle' : 'activity-explorer-toggle')?.focus();
}

/** The covered nodes are direct children of the shell row; a child swap there
 *  (BottomPanel switching `.wb-panel` and `.wb-panel-shut`) means the cover is stale. */
function watchShell(onChange: () => void): () => void {
  const shell = document.querySelector(SHELL_SELECTOR);
  if (!shell || typeof MutationObserver === 'undefined') return () => undefined;
  const observer = new MutationObserver(onChange);
  observer.observe(shell, { childList: true });
  return () => observer.disconnect();
}

/** True only inside the overlay band, live across resizes. Server-side and
 *  stacked/docked widths report false so no scrim ever renders there. */
function useOverlayBand(): boolean {
  const [inBand, setInBand] = useState(
    () => typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia(OVERLAY_BAND).matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(OVERLAY_BAND);
    const onChange = () => setInBand(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return inBand;
}

/** Band scrim: dims the centre while an Explorer/dock overlay floats above
 *  it. Click closes the topmost overlay (dock first, mirroring the ESC LIFO
 *  in useOverlayPanels) and returns focus to that panel's activity toggle.
 *  The approval card lives inside the dock drawer, so the scrim's lower
 *  z-index keeps the card interactive without any modal code. */
export default function OverlayScrim({
  dockOpen,
  explorerOpen,
  onToggleDock,
  onToggleExplorer,
}: {
  readonly dockOpen: boolean;
  readonly explorerOpen: boolean;
  readonly onToggleDock: (open: boolean) => void;
  readonly onToggleExplorer: (open: boolean) => void;
}) {
  const { t } = useLocale();
  const inBand = useOverlayBand();
  const active = inBand && (dockOpen || explorerOpen);
  const topmost: 'dock' | 'explorer' = dockOpen ? 'dock' : 'explorer';
  const topmostRef = useRef(topmost);
  topmostRef.current = topmost;
  // The scrim only dims what it covers; Tab would still walk into it. Inert
  // removes the covered centre and bottom panel from the tab order and the
  // accessibility tree for exactly as long as the scrim renders. Focus inside
  // a covered node moves to the open drawer's toggle first, and nodes the
  // shell swaps in meanwhile (the bottom panel opening) are covered as well.
  useEffect(() => {
    if (!active) return undefined;
    return applyInertCover({
      doc: document,
      selectors: COVERED_SELECTORS,
      rescueFocus: () => focusToggle(topmostRef.current),
      watch: watchShell,
    });
  }, [active]);
  if (!active) return null;
  const closeTopmost = () => {
    if (topmost === 'dock') onToggleDock(false);
    else onToggleExplorer(false);
    focusToggle(topmost);
  };
  return (
    <button
      type="button"
      className="wb-scrim"
      data-scrim
      aria-label={topmost === 'dock' ? t('shell.dockHide') : t('shell.explorerHide')}
      onClick={closeTopmost}
    />
  );
}
