import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { IconButton } from '../ui/IconButton';
import { PixelIcon, type PixelIconName } from '../ui/PixelIcon';
import { useLocale } from '../i18n/index.ts';
import type { WorkbenchView } from './useWorkbenchLayout';
import OverlayScrim from './OverlayScrim';

const ORDER: readonly { readonly view: WorkbenchView; readonly icon: PixelIconName; readonly shortcut: string; readonly keys: string }[] = [
  { view: 'workspace', icon: 'case', shortcut: 'Ctrl+1', keys: 'Control+1' },
  { view: 'results', icon: 'results', shortcut: 'Ctrl+2', keys: 'Control+2' },
  { view: 'run', icon: 'run', shortcut: 'Ctrl+3', keys: 'Control+3' },
  { view: 'settings', icon: 'settings', shortcut: 'Ctrl+4', keys: 'Control+4' },
];

function labelFor(view: WorkbenchView, t: (key: 'nav.workspace' | 'nav.results' | 'nav.run' | 'nav.settings') => string | undefined): string {
  return t(`nav.${view}`) ?? view;
}

export default function ActivityBar({
  view,
  onSelect,
  explorerOpen,
  dockOpen,
  onToggleExplorer,
  onToggleDock,
}: {
  readonly view: WorkbenchView;
  readonly onSelect: (next: WorkbenchView) => void;
  readonly explorerOpen: boolean;
  readonly dockOpen: boolean;
  readonly onToggleExplorer: (open: boolean) => void;
  readonly onToggleDock: (open: boolean) => void;
}) {
  const { t } = useLocale();
  const barRef = useRef<HTMLElement | null>(null);
  const indicatorRef = useRef<HTMLSpanElement | null>(null);

  const place = useCallback(() => {
    const bar = barRef.current;
    const indicator = indicatorRef.current;
    if (!bar || !indicator) return;
    const active = bar.querySelector<HTMLButtonElement>(`[data-view="${view}"]`)?.closest('button');
    if (!active) return;
    indicator.style.transform = `translateY(${active.offsetTop}px)`;
    indicator.style.height = `${active.offsetHeight}px`;
  }, [view]);

  useLayoutEffect(place);

  // The select block follows the active item when fonts, labels or the UI scale
  // change its size after the first paint.
  useEffect(() => {
    const bar = barRef.current;
    if (!bar || typeof ResizeObserver !== 'function') return;
    const observer = new ResizeObserver(place);
    observer.observe(bar);
    bar.querySelectorAll('button').forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [place]);

  const explorerLabel = explorerOpen ? t('shell.explorerHide') : t('shell.explorerShow');
  const dockLabel = dockOpen ? t('shell.dockHide') : t('shell.dockShow');
  return (
    <>
    <nav ref={barRef} className="wb-activity" aria-label={t('shell.activityNav')}>
      <span ref={indicatorRef} className="wb-activity-indicator" aria-hidden="true" />
      {ORDER.map((entry) => (
        <IconButton
          key={entry.view}
          label={labelFor(entry.view, t)}
          title={`${labelFor(entry.view, t)} (${entry.shortcut})`}
          pressed={entry.view === view}
          keyshortcuts={entry.keys}
          visibleLabel={labelFor(entry.view, t)}
          onClick={() => onSelect(entry.view)}
        >
          <span data-view={entry.view} className="wb-activity-icon">
            <PixelIcon name={entry.icon} size={24} />
          </span>
        </IconButton>
      ))}
      <span className="wb-activity-sep" aria-hidden="true" />
      <IconButton
        label={explorerLabel}
        title={explorerLabel}
        expanded={explorerOpen}
        controls="workbench-explorer"
        toggleId="activity-explorer-toggle"
        toggleClass="wb-activity-overlay-toggle"
        visibleLabel={explorerLabel}
        onClick={() => onToggleExplorer(!explorerOpen)}
      >
        <span className="wb-toggle-chevron" data-open={explorerOpen || undefined} aria-hidden="true" />
      </IconButton>
      <IconButton
        label={dockLabel}
        title={dockLabel}
        expanded={dockOpen}
        controls="workbench-chat-dock"
        toggleId="activity-dock-toggle"
        toggleClass="wb-activity-overlay-toggle"
        visibleLabel={dockLabel}
        onClick={() => onToggleDock(!dockOpen)}
      >
        <span className="wb-toggle-chevron" data-open={dockOpen || undefined} aria-hidden="true" />
      </IconButton>
    </nav>
    <OverlayScrim
      dockOpen={dockOpen}
      explorerOpen={explorerOpen}
      onToggleDock={onToggleDock}
      onToggleExplorer={onToggleExplorer}
    />
    </>
  );
}
