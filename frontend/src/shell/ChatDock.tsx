import { useRef } from 'react';
import { IconButton } from '../ui/IconButton';
import { PanelResizeHandle } from '../PanelResizeHandle';
import { PixelIcon } from '../ui/PixelIcon';
import { PaneDecor } from '../ui/PaneDecor';
import { useLocale } from '../i18n/index.ts';

export default function ChatDock({
  open,
  onToggle,
  children,
}: {
  readonly open: boolean;
  readonly onToggle: (open: boolean) => void;
  readonly children: React.ReactNode;
}) {
  const { t } = useLocale();
  const dockRef = useRef<HTMLElement | null>(null);
  if (!open) {
    return (
      <div className="wb-dock-shut">
        <IconButton label={t('shell.dockShow')} title={t('shell.dockShow')} onClick={() => onToggle(true)}>
          <PixelIcon name="chevron" size={18} />
        </IconButton>
      </div>
    );
  }
  return (
    <>
      <aside ref={dockRef} id="workbench-chat-dock" className="wb-dock" aria-label={t('shell.dockLabel')} data-coord="C1">
        <PaneDecor />
        <div className="wb-pane-head">
          <span className="wb-pane-idx" aria-hidden="true">03</span>
          <span>{t('shell.dockLabel')}</span>
          <PixelIcon name="bar" size={12} className="pixel-sep" />
          <span className="wb-spacer" aria-hidden="true" />
          <IconButton label={t('shell.dockHide')} title={t('shell.dockHide')} onClick={() => onToggle(false)}>
            <PixelIcon name="collapse" size={18} />
          </IconButton>
        </div>
        <div className="wb-dock-body">{children}</div>
      </aside>
      <PanelResizeHandle
        targetRef={dockRef}
        targetId="workbench-chat-dock"
        label={t('shell.dockResize')}
        storageKey="olga-companion.dock.width"
        defaultWidth={384}
        minWidth={300}
        maxWidth={560}
        direction="grow-left"
        className="wb-dock-resizer"
      />
    </>
  );
}
