export const SESSION_PAGE_SIZE = 50;

export type SessionWindow<T> = {
  readonly visible: readonly T[];
  readonly remaining: number;
};

export function sessionWindow<T>(sessions: readonly T[], requestedCount: number): SessionWindow<T> {
  const visibleCount = Math.min(sessions.length, Math.max(SESSION_PAGE_SIZE, requestedCount));
  return {
    visible: sessions.slice(0, visibleCount),
    remaining: sessions.length - visibleCount,
  };
}
