import type { SessionMeta } from './session';

function queryTokens(query: string): readonly string[] {
  return query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
}

export function filterSessions(
  sessions: readonly SessionMeta[],
  query: string,
): readonly SessionMeta[] {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return sessions;

  return sessions.filter((session) => {
    const searchable = `${session.title || 'Untitled'} ${session.session_id}`.toLocaleLowerCase();
    return tokens.every((token) => searchable.includes(token));
  });
}
