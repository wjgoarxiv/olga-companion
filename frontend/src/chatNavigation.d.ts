export interface ChatNavigationSession {
  readonly session_id: string;
  readonly title: string;
}

export interface ChatNavigationPorts<Session extends ChatNavigationSession = ChatNavigationSession> {
  bootstrap(): Promise<{
    readonly sessionId: string;
    readonly sessions: readonly Session[];
    readonly records: readonly Record<string, unknown>[];
  }>;
  commit(id: string): void;
  createSession(title: string): Promise<string>;
  deleteSession(id: string): Promise<unknown>;
  error(error: Error): void;
  fetchHistory(id: string): Promise<readonly Record<string, unknown>[]>;
  fetchSessions(): Promise<readonly Session[]>;
  forget(): void;
  isBusy(): boolean;
  remember(id: string): void;
  reset(): void;
  restore(records: readonly Record<string, unknown>[]): void;
  setSessions(sessions: readonly Session[]): void;
}

export interface ChatNavigator {
  readonly currentId: string;
  ensureSession(titleHint?: string): Promise<string | null>;
  load(id: string): Promise<void>;
  newChat(): void;
  remove(id: string): Promise<void>;
  startInitial(): Promise<void>;
}

export function chatTitle(message: string | null | undefined): string;

export function createChatNavigator<Session extends ChatNavigationSession>(
  ports: ChatNavigationPorts<Session>,
): ChatNavigator;
