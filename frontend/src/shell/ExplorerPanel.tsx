import { useRef, useState } from 'react';
import NativeContextActions from '../NativeContextActions';
import { useExplorerFilter } from '../explorerFilter';
import { useLocale } from '../i18n/index.ts';
import { PanelResizeHandle } from '../PanelResizeHandle';
import { splitNameHalves } from '../fileNameDisplay';
import { Icon, type IconName } from '../ui/Icon';
import { PaneDecor } from '../ui/PaneDecor';
import { IconButton } from '../ui/IconButton';
import { requestTabPreview } from './workspaceEvents';
import type { NativeSelectedContext, WorkspaceCase } from '../session';

const EXPLORER_WIDTH_KEY = 'olga-companion.explorer.width';
const EXPLORER_MIN_WIDTH = 200;
const EXPLORER_MAX_WIDTH = 480;

/** Fresh default follows the viewport: ~280 px on wide screens, 248 below. */
function defaultExplorerWidth(): number {
  if (typeof window === 'undefined') return 248;
  return window.innerWidth >= 1440 ? 280 : 248;
}

type ExplorerGroup = 'cases' | 'pvt' | 'outputs';

const GROUP_ORDER: readonly ExplorerGroup[] = ['cases', 'pvt', 'outputs'];

const GROUP_KEYS = {
  cases: 'explorer.groupCases',
  pvt: 'explorer.groupPvt',
  outputs: 'explorer.groupOutputs',
} as const;

function groupOf(item: WorkspaceCase): ExplorerGroup {
  if (item.suffix === '.genkey') return 'cases';
  if (item.suffix === '.tab') return 'pvt';
  return 'outputs';
}

function iconFor(item: WorkspaceCase): IconName {
  if (item.suffix === '.genkey') return 'file';
  if (item.suffix === '.tab') return 'fluid';
  if (item.suffix === '.tpl' || item.suffix === '.ppl') return 'graph';
  return 'node';
}

export default function ExplorerPanel({
  cases,
  activeName,
  onPick,
  contextGeneration,
  onContextSelected,
  open,
  onToggle,
}: {
  readonly cases: WorkspaceCase[];
  readonly activeName: string | null;
  readonly onPick: (rel: string) => void;
  readonly contextGeneration: number;
  readonly onContextSelected: (context: NativeSelectedContext) => void | Promise<void>;
  readonly open: boolean;
  readonly onToggle: (open: boolean) => void;
}) {
  const { t } = useLocale();
  const explorerRef = useRef<HTMLElement | null>(null);
  const [filter, setFilter] = useExplorerFilter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [itemMenu, setItemMenu] = useState<string | null>(null);
  if (!open) {
    return (
      <div className="wb-explorer-shut">
        <IconButton label={t('shell.explorerShow')} title={t('shell.explorerShow')} onClick={() => onToggle(true)}>
          <Icon name="chevron" size={18} />
        </IconButton>
      </div>
    );
  }
  const needle = filter.trim().toLowerCase();
  const visible = needle === '' ? cases : cases.filter((item) => item.name.toLowerCase().includes(needle));
  /** .genkey activates the case; .tab previews read-only without touching it. */
  function openItem(item: WorkspaceCase) {
    setItemMenu(null);
    if (item.suffix === '.tab') {
      window.dispatchEvent(requestTabPreview(item.rel));
      return;
    }
    onPick(item.rel);
  }
  const groups = GROUP_ORDER.map((group) => ({
    group,
    items: visible.filter((item) => groupOf(item) === group),
  })).filter((entry) => entry.items.length > 0);
  return (
    <>
    <aside ref={explorerRef} id="workbench-explorer" className="wb-explorer" aria-label={t('shell.explorer')} data-coord="A1">
      <PaneDecor />
      <div className="wb-pane-head">
        <span className="wb-pane-idx" aria-hidden="true">01</span>
        <span>{t('shell.explorer')}</span>
        <span className="pixel-sep" aria-hidden="true" />
        <span className="wb-spacer" aria-hidden="true" />
        <IconButton
          label={t('explorer.workspaceActions')}
          title={t('explorer.workspaceActions')}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <Icon name="folder" size={18} />
        </IconButton>
        <IconButton label={t('shell.explorerHide')} title={t('shell.explorerHide')} onClick={() => onToggle(false)}>
          <Icon name="collapse" size={18} />
        </IconButton>
      </div>
      {menuOpen && (
        <div className="wb-explorer-menu" role="dialog" aria-label={t('explorer.workspaceActions')}>
          <NativeContextActions contextGeneration={contextGeneration} onSelected={onContextSelected} />
        </div>
      )}
      <div className="wb-explorer-filter">
        <input
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder={t('explorer.filterPlaceholder')}
          aria-label={t('explorer.filterLabel')}
        />
      </div>
      {cases.length === 0 ? (
        <p className="wb-explorer-empty">{t('workspace.emptyChrome')}</p>
      ) : (
        <div className="wb-explorer-tree" role="tree" aria-label={t('explorer.treeLabel')}>
          {groups.map(({ group, items }) => (
            <section key={group} className="wb-explorer-group" role="group" aria-label={t(GROUP_KEYS[group])}>
              <h3 className="wb-explorer-group-head">
                {t(GROUP_KEYS[group])}
                <span className="wb-explorer-group-count num">{items.length}</span>
              </h3>
              <ul>
                {items.map((item) => {
                  const stem = item.suffix !== '' && item.name.endsWith(item.suffix)
                    ? item.name.slice(0, -item.suffix.length)
                    : item.name;
                  const { head, tail } = splitNameHalves(stem || item.name);
                  // The group header already names homogeneous types, so the
                  // suffix column stays only for mixed/unknown types.
                  const showSuffix = group !== 'cases' && group !== 'pvt';
                  return (
                    <li key={item.rel}>
                      <button
                        type="button"
                        className="wb-explorer-item"
                        aria-current={item.name === activeName ? 'true' : undefined}
                        onClick={() => openItem(item)}
                        onContextMenu={(event) => {
                          event.preventDefault();
                          setItemMenu(item.rel);
                        }}
                        title={item.name}
                        aria-label={`${item.name}, ${(item.size / 1024).toFixed(1)} KB`}
                      >
                        <Icon name={iconFor(item)} size={18} />
                        <span className="wb-explorer-name">
                          <span className="wb-explorer-name-head">{head}</span>
                          <span className="wb-explorer-name-tail">{tail}</span>
                        </span>
                        {showSuffix && item.suffix && <span className="wb-explorer-ext">{item.suffix}</span>}
                        <span className="wb-explorer-meta num">{(item.size / 1024).toFixed(0)} KB</span>
                      </button>
                      {itemMenu === item.rel && (
                        <div className="wb-explorer-item-menu" role="menu" aria-label={item.name}>
                          <button
                            type="button"
                            role="menuitem"
                            onClick={() => openItem(item)}
                          >
                            {item.suffix === '.tab' ? t('explorer.previewTable') : t('explorer.openCase')}
                          </button>
                          <button type="button" role="menuitem" onClick={() => setItemMenu(null)}>
                            {t('explorer.closeMenu')}
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
          {visible.length === 0 && (
            <p className="wb-explorer-empty">{t('explorer.noMatchFor', { needle: filter })}</p>
          )}
        </div>
      )}
    </aside>
    <PanelResizeHandle
      targetRef={explorerRef}
      targetId="workbench-explorer"
      label={t('explorer.resize')}
      storageKey={EXPLORER_WIDTH_KEY}
      defaultWidth={defaultExplorerWidth()}
      minWidth={EXPLORER_MIN_WIDTH}
      maxWidth={EXPLORER_MAX_WIDTH}
      direction="grow-right"
      className="wb-explorer-resizer"
    />
    </>
  );
}
