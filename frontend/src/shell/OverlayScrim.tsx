import { useEffect, useState } from 'react';
import { useLocale } from '../i18n/index.ts';

const OVERLAY_BAND = '(min-width: 769px) and (max-width: 1023px)';

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
  if (!inBand || (!dockOpen && !explorerOpen)) return null;
  const topmost = dockOpen ? 'dock' : 'explorer';
  const closeTopmost = () => {
    if (topmost === 'dock') {
      onToggleDock(false);
      document.getElementById('activity-dock-toggle')?.focus();
    } else {
      onToggleExplorer(false);
      document.getElementById('activity-explorer-toggle')?.focus();
    }
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
