import { PanelRightOpen, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import type { SessionMeta } from './session';
import { modifiedLabel } from './resultPresentation';
import { filterSessions } from './sessionSearch';
import { SESSION_PAGE_SIZE, sessionWindow } from './sessionWindow';

/** The chat-history switcher, labelled "Chats" (it lists past conversations, not
 *  the ambiguous "Sessions"). Loads one on click and deletes one on ✕ — reusing
 *  the existing /api/chat store. Rehydrated evidence is not restored (only
 *  user/assistant text + which tools ran). */
export default function SessionMenu({
  sessions,
  currentId,
  busy,
  onSelect,
  onDelete
}: {
  readonly sessions: readonly SessionMeta[];
  readonly currentId: string;
  readonly busy: boolean;
  readonly onSelect: (id: string) => void;
  readonly onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [visibleCount, setVisibleCount] = useState(SESSION_PAGE_SIZE);
  const { t, locale } = useLocale();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const matchingSessions = filterSessions(sessions, query);
  const visibleSessions = sessionWindow(matchingSessions, visibleCount);

  function closeHistory(): void {
    setOpen(false);
    setQuery('');
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }

  useEffect(() => {
    setVisibleCount(SESSION_PAGE_SIZE);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeHistory();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  return (
    <div className="session-menu">
      <button
        ref={triggerRef}
        type="button"
        className="session-rail-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="chat-history-rail"
        aria-label={open ? t('history.closeHistory') : t('history.openHistory')}
        title={open ? t('history.closeHistory') : t('history.openHistory')}
      >
        <PanelRightOpen aria-hidden="true" focusable="false" strokeWidth={1.8} />
        <span>{t('chat.chats')}</span>
      </button>
      {open && (
        <>
          <button type="button" className="session-rail-scrim" onClick={closeHistory} aria-label={t('history.closeHistory')} />
          <aside id="chat-history-rail" className="session-rail" aria-label={t('history.historyTitle')}>
            <header className="session-rail-header">
              <div>
                <strong>{t('history.historyTitle')}</strong>
                <span>{query.trim() ? t('history.searchResults') : t('history.savedConversations')}</span>
              </div>
              <button type="button" className="session-rail-close" onClick={closeHistory} aria-label={t('history.closeHistory')}>
                <X aria-hidden="true" focusable="false" strokeWidth={1.8} />
              </button>
            </header>
            {sessions.length > 0 && (
              <div className="session-search-wrap">
                <input
                  className="session-search"
                  type="search"
                  aria-label={t('history.searchAria')}
                  placeholder={t('history.searchPlaceholder')}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
            )}
            {sessions.length === 0 && <p className="chrome-hint">{t('history.noPastChats')}</p>}
            <ul className="session-list">
              {sessions.length > 0 && matchingSessions.length === 0 && (
                <li className="session-search-empty" role="status">
                  <strong>{t('history.noChatsMatch')}</strong>
                  <span>{t('history.tryTitleOrId')}</span>
                </li>
              )}
              {visibleSessions.visible.map((s) => (
                <li key={s.session_id} className="session-row">
                  <button
                    type="button"
                    className={`session-item${s.session_id === currentId ? ' current' : ''}`}
                    onClick={() => {
                      onSelect(s.session_id);
                      closeHistory();
                    }}
                  >
                    <span className="session-title">{s.title || t('history.untitled')}</span>
                    <span className="session-id">{s.updated_ms ? `${modifiedLabel(s.updated_ms * 1_000_000, locale)} · ` : ''}{s.session_id.slice(0, 8)}</span>
                  </button>
                  <button
                    type="button"
                    className="session-delete"
                    title={busy && s.session_id === currentId ? t('history.cannotDeleteActive') : t('history.deleteChat')}
                    aria-label={t('history.deleteChatTitle', { title: s.title || s.session_id.slice(0, 8) })}
                    disabled={busy && s.session_id === currentId}
                    onClick={() => onDelete(s.session_id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            {visibleSessions.remaining > 0 && (
              <button
                type="button"
                className="session-item session-more"
                onClick={() => setVisibleCount((count) => count + SESSION_PAGE_SIZE)}
              >
                <span>{t('history.loadMore')}</span>
              </button>
            )}
          </aside>
        </>
      )}
    </div>
  );
}
