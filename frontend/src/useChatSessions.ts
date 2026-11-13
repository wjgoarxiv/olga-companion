import { useRef, useState } from 'react';
import * as session from './session';
import { bootstrapChatSession, visibleChatSessions } from './chatSessionBootstrap';
import { createChatNavigator } from './chatNavigation';
import { readLocalStorage, removeLocalStorage, writeLocalStorage } from './safeLocalStorage';
import { rehydrateTimeline, type TimelineItem } from './timeline';

const LAST_SESSION_KEY = 'olga_last_chat_session';

interface UseChatSessionsArgs {
  readonly isBusy: () => boolean;
  readonly onError: (error: unknown) => void;
  readonly onReset: () => void;
  readonly onRestore: (items: TimelineItem[]) => void;
}

export function useChatSessions({ isBusy, onError, onReset, onRestore }: UseChatSessionsArgs) {
  const [sessionId, setSessionId] = useState('');
  const [sessions, setSessions] = useState<session.SessionMeta[]>([]);
  // Ports read the latest props through this ref; the navigator itself is created once.
  const latest = useRef({ isBusy, onError, onReset, onRestore });
  latest.current = { isBusy, onError, onReset, onRestore };
  const navigatorRef = useRef<ReturnType<typeof createChatNavigator<session.SessionMeta>> | null>(null);
  navigatorRef.current ??= createChatNavigator<session.SessionMeta>({
    bootstrap: () => bootstrapChatSession({
      preferredId: readLocalStorage(LAST_SESSION_KEY) ?? '',
      list: session.fetchSessions,
      history: session.fetchSessionHistory,
    }),
    commit: setSessionId,
    createSession: session.newSession,
    deleteSession: session.deleteSession,
    error: (error) => latest.current.onError(error),
    fetchHistory: session.fetchSessionHistory,
    fetchSessions: session.fetchSessions,
    forget: () => removeLocalStorage(LAST_SESSION_KEY),
    isBusy: () => latest.current.isBusy(),
    remember: (id) => writeLocalStorage(LAST_SESSION_KEY, id),
    reset: () => latest.current.onReset(),
    restore: (records) => latest.current.onRestore(rehydrateTimeline([...records])),
    setSessions: (items) => setSessions([...visibleChatSessions([...items])]),
  });
  const navigator = navigatorRef.current;

  return {
    currentId: () => navigator.currentId,
    deleteChat: navigator.remove,
    ensureSession: navigator.ensureSession,
    loadSession: navigator.load,
    newChat: async () => navigator.newChat(),
    sessionId,
    sessions,
    startInitialSession: navigator.startInitial,
  };
}
