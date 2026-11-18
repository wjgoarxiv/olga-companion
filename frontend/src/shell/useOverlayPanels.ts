import { useEffect } from 'react';

const OVERLAY_BAND = '(min-width: 769px) and (max-width: 1023px)';

function inOverlayBand(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(OVERLAY_BAND).matches;
}

/** Overlay-band dismissal: Escape closes the topmost open overlay (the dock
 *  renders above the Explorer) and returns focus to its activity-bar toggle.
 *  The stacked below-768 layout keeps everything in flow, so Escape stays
 *  quiet there; at 1024 and up the panels are docked, not overlays. */
export function useOverlayPanels({
  dockOpen,
  explorerOpen,
  setDockOpen,
  setExplorerOpen,
}: {
  readonly dockOpen: boolean;
  readonly explorerOpen: boolean;
  readonly setDockOpen: (open: boolean) => void;
  readonly setExplorerOpen: (open: boolean) => void;
}): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || !inOverlayBand()) return;
      if (dockOpen) {
        setDockOpen(false);
        document.getElementById('activity-dock-toggle')?.focus();
      } else if (explorerOpen) {
        setExplorerOpen(false);
        document.getElementById('activity-explorer-toggle')?.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [dockOpen, explorerOpen, setDockOpen, setExplorerOpen]);
}
