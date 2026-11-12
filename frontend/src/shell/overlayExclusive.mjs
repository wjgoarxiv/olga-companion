export const OVERLAY_BAND_QUERY = '(min-width: 769px) and (max-width: 1023px)';

/** True for viewport widths where the dock and Explorer float as overlays. */
export function isOverlayBandWidth(width) {
  return width >= 769 && width <= 1023;
}

/** Live check of the band against the current window; false where there is no window. */
export function inOverlayBandNow() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(OVERLAY_BAND_QUERY).matches;
}

/** Showing a centre view from inside the dock: in the band the dock floats over
 *  the centre, so it closes first or the view would open hidden behind it. */
export function revealCentreView({ inBand, closeDock, selectView }, view) {
  if (inBand) closeDock();
  selectView(view);
}

/** Inside the overlay band only one drawer may be open. `changed` names the
 *  pane whose state just changed ('dock' | 'explorer'); opening it closes the
 *  other. With `changed` null (first load, or the window shrinking into the
 *  band) the dock wins because it carries the approval card. Outside the band
 *  both panes are docked and stay independent. */
export function resolveOverlayExclusive(open, changed, inBand) {
  const { dockOpen, explorerOpen } = open;
  if (!inBand || !dockOpen || !explorerOpen) return { dockOpen, explorerOpen };
  if (changed === 'explorer') return { dockOpen: false, explorerOpen: true };
  return { dockOpen: true, explorerOpen: false };
}
