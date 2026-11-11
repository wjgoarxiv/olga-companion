import { useRef, useSyncExternalStore } from 'react';
import { Tabs } from '../ui/Tabs';
import { IconButton } from '../ui/IconButton';
import { PixelIcon } from '../ui/PixelIcon';
import { PaneDecor } from '../ui/PaneDecor';
import { HeightResizer, resolvePanelHeight } from './HeightResizer';
import { useLocale } from '../i18n/index.ts';
import ProblemsPanel from './ProblemsPanel';
import { RunConsolePanel } from '../RunConsolePanel';
import { getCaseProblemsSnapshot, subscribeCaseProblems } from './caseProblems';
import type { BottomPanelTab } from './useWorkbenchLayout';

const TABS: readonly BottomPanelTab[] = ['problems', 'console', 'outputs'];

export default function BottomPanel({
  open,
  onToggle,
  tab,
  onTab,
  onFocusNode,
}: {
  readonly open: boolean;
  readonly onToggle: (open: boolean) => void;
  readonly tab: BottomPanelTab;
  readonly onTab: (tab: BottomPanelTab) => void;
  readonly onFocusNode: (nodeId: string) => void;
}) {
  const { t } = useLocale();
  const panelRef = useRef<HTMLElement | null>(null);
  const problems = useSyncExternalStore(subscribeCaseProblems, getCaseProblemsSnapshot);
  const items = TABS.map((id) => ({
    id,
    label: t(`shell.${id}`) ?? id,
    badge: id === 'problems' && problems.length > 0 ? String(problems.length) : undefined,
  }));
  if (!open) {
    return (
      <div className="wb-panel-shut">
        <IconButton label={t('shell.panelShow')} title={t('shell.panelShow')} onClick={() => onToggle(true)}>
          <PixelIcon name="chevron" size={18} />
        </IconButton>
      </div>
    );
  }
  return (
    <>
      <HeightResizer
        targetRef={panelRef}
        targetId="workbench-bottom-panel"
        label={t('shell.panelResize')}
        storageKey="olga-companion.panel.height"
        defaultHeight={168}
        minHeight={120}
        maxHeight={480}
        className="wb-panel-resizer"
      />
      {/* Declarative first-paint height (same stored-or-default source the
          resizer owns); the effect only reconciles later updates. */}
      <section
        ref={panelRef}
        id="workbench-bottom-panel"
        className="wb-panel"
        aria-label={t('shell.panelLabel')}
        data-coord="B2"
        style={{ height: `${resolvePanelHeight('olga-companion.panel.height', 168, 120, 480)}px` }}
      >
        <PaneDecor />
        <div className="wb-panel-bar">
          <span className="wb-pane-idx wb-panel-idx" aria-hidden="true">04</span>
          <PixelIcon name="bar" size={12} className="pixel-sep pane-head-sep" />
          <Tabs
            items={items}
            value={tab}
            onChange={(next) => {
              if (next === 'problems' || next === 'console' || next === 'outputs') onTab(next);
            }}
            ariaLabel={t('shell.panelLabel')}
          >
            {tab === 'problems' ? (
              <ProblemsPanel onFocusNode={onFocusNode} />
            ) : tab === 'console' ? (
              <RunConsolePanel />
            ) : (
              <p className="wb-panel-empty">{t('shell.outputsEmpty')}</p>
            )}
          </Tabs>
          <IconButton label={t('shell.panelHide')} title={t('shell.panelHide')} onClick={() => onToggle(false)}>
            <PixelIcon name="collapse" size={18} />
          </IconButton>
        </div>
      </section>
    </>
  );
}
