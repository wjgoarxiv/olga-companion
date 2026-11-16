import { Activity, FolderOpen, MessageSquare, Play, Settings, type LucideIcon } from 'lucide-react';
import { useRef } from 'react';
import { useLocale } from './i18n/index.ts';
import { PanelResizeHandle } from './PanelResizeHandle';

export interface NavItem<Id extends string = string> {
  readonly id: Id;
  readonly label: string;
  readonly icon?: string;
  readonly badge?: string;
  readonly gated?: boolean;
}

const navIcons: Readonly<Record<string, LucideIcon>> = {
  chat: MessageSquare,
  workspace: FolderOpen,
  results: Activity,
  run: Play,
  settings: Settings
};

function NavIcon({ id }: { readonly id: string }) {
  const Icon = navIcons[id] ?? Activity;
  return <Icon className="nav-icon" aria-hidden="true" focusable="false" strokeWidth={1.8} />;
}

export default function Sidebar<Id extends string>({
  view,
  items,
  onSelect
}: {
  view: Id;
  items: readonly NavItem<Id>[];
  onSelect: (id: Id) => void;
}) {
  const navRef = useRef<HTMLElement | null>(null);
  const { t } = useLocale();
  return (
    <>
      <nav ref={navRef} id="primary-workspace-navigation" className="shell-nav" aria-label={t('sidebar.navAria')}>
        <div className="sidebar-nav-items">
          <p className="sidebar-nav-heading" aria-hidden="true">{t('sidebar.sectionMenu')}</p>
          {items.map((it) => (
            <button
              key={it.id}
              type="button"
              className={`nav-item${view === it.id ? ' active' : ''}${it.gated ? ' gated' : ''}`}
              aria-label={it.label}
              aria-current={view === it.id ? 'page' : undefined}
              title={it.label}
              onClick={() => onSelect(it.id)}
            >
              <NavIcon id={it.id} />
              <span className="nav-label">{it.label}</span>
              {it.badge && <span className="nav-badge">{it.badge}</span>}
            </button>
          ))}
        </div>
        <footer className="sidebar-footer" aria-label={t('sidebar.creditAria')}>
          <span className="sidebar-credit-label">{t('sidebar.creditLabel')}</span>
          <a
            className="sidebar-credit-link"
            href="https://github.com/wjgoarxiv"
            target="_blank"
            rel="noreferrer"
            aria-label={t('sidebar.githubAria')}
          >
            <img
              className="sidebar-credit-lockup"
              src="/woojin-go-lockup-horizontal.png"
              alt=""
              aria-hidden="true"
            />
          </a>
        </footer>
      </nav>
      <PanelResizeHandle
        targetRef={navRef}
        targetId="primary-workspace-navigation"
        label={t('sidebar.resizeLabel')}
        storageKey="olga_panel_primary_navigation"
        defaultWidth={210}
        minWidth={156}
        maxWidth={360}
        className="shell-nav-resizer"
      />
    </>
  );
}
