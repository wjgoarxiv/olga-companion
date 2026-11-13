import type { SessionMeta } from './chatSessionApi';

export interface ChatBootstrapDependencies {
  readonly preferredId: string;
  readonly list: () => Promise<readonly SessionMeta[]>;
  readonly history: (id: string) => Promise<readonly Record<string, unknown>[]>;
}

export interface ChatBootstrapResult {
  readonly sessionId: string;
  readonly sessions: readonly SessionMeta[];
  readonly records: readonly Record<string, unknown>[];
  readonly created: boolean;
}

export function visibleChatSessions(sessions: readonly SessionMeta[]): readonly SessionMeta[] {
  return sessions.filter((candidate) => (
    candidate.tombstoned !== true
    && candidate.deleted !== true
    && candidate.state !== 'tombstoned'
    && candidate.state !== 'deleted'
  ));
}

export function selectRestorableSession(
  sessions: readonly SessionMeta[],
  preferredId: string,
): SessionMeta | undefined {
  const visible = visibleChatSessions(sessions);
  return visible.find((candidate) => candidate.session_id === preferredId) ?? visible[0];
}

let activeBootstrap: Promise<ChatBootstrapResult> | null = null;

async function performBootstrap(
  dependencies: ChatBootstrapDependencies,
): Promise<ChatBootstrapResult> {
  const sessions = visibleChatSessions(await dependencies.list());
  const selected = selectRestorableSession(sessions, dependencies.preferredId);
  if (selected) {
    return {
      sessionId: selected.session_id,
      sessions,
      records: await dependencies.history(selected.session_id),
      created: false,
    };
  }
  return {
    sessionId: '',
    sessions,
    records: [],
    created: false,
  };
}

export function bootstrapChatSession(
  dependencies: ChatBootstrapDependencies,
): Promise<ChatBootstrapResult> {
  if (activeBootstrap) return activeBootstrap;
  const pending = performBootstrap(dependencies);
  activeBootstrap = pending;
  void pending.then(
    () => { if (activeBootstrap === pending) activeBootstrap = null; },
    () => { if (activeBootstrap === pending) activeBootstrap = null; },
  );
  return pending;
}
