import { createRequestEpoch } from './requestEpoch.mjs';

const DEFAULT_TITLE = 'OLGA session';
const TITLE_LIMIT = 48;

/** A readable history title from the first question; whitespace collapsed, bounded. */
export function chatTitle(message) {
  const text = String(message ?? '').replace(/\s+/gu, ' ').trim();
  if (!text) return DEFAULT_TITLE;
  const chars = [...text];
  return chars.length > TITLE_LIMIT ? `${chars.slice(0, TITLE_LIMIT - 1).join('')}…` : text;
}

/**
 * Conversation navigation with last-intent-wins semantics. Every awaited step
 * (initial restore, load, create, delete, list refresh) re-checks the epoch before
 * it may change visible state, so a slow earlier response never overwrites the
 * chat the user is looking at.
 */
export function createChatNavigator(ports) {
  const navigation = createRequestEpoch();
  const lists = createRequestEpoch();
  let createPending = null;
  let currentId = '';
  let loadingId = '';
  const deleting = new Set();

  function commit(id) {
    currentId = id;
    if (id) createPending = null;
    ports.commit(id);
  }

  function startCreate(titleHint) {
    const pending = { adopted: false, promise: null, waiters: 0 };
    pending.promise = ports.createSession(chatTitle(titleHint)).catch((error) => {
      if (createPending === pending) createPending = null;
      throw error;
    });
    return pending;
  }

  // A conversation created for a send the user walked away from would otherwise
  // reopen later as an empty chat carrying the title of a message never sent. The
  // last waiter decides, because a newer send may still share the same create.
  function discardUnused(pending, id) {
    if (pending.waiters > 0 || pending.adopted || id === currentId) return;
    if (createPending === pending) createPending = null;
    ports.deleteSession(id).then(refreshSessions, () => undefined);
  }

  function refreshSessions() {
    const request = lists.begin();
    ports.fetchSessions().then((items) => {
      if (lists.isCurrent(request)) ports.setSessions(items);
    }, () => undefined);
  }

  function reportError(error) {
    ports.error(error instanceof Error ? error : new Error(String(error)));
  }

  return {
    get currentId() {
      return currentId;
    },
    async startInitial() {
      const request = navigation.begin();
      const listRequest = lists.begin();
      const restored = await ports.bootstrap();
      // The saved-chat list is still true even when the user has already moved on.
      if (lists.isCurrent(listRequest)) ports.setSessions(restored.sessions);
      if (!navigation.isCurrent(request)) return;
      lists.invalidate();
      commit(restored.sessionId);
      if (restored.sessionId) ports.remember(restored.sessionId);
      ports.restore(restored.records);
    },
    newChat() {
      if (ports.isBusy()) return;
      navigation.invalidate();
      createPending = null;
      commit('');
      ports.forget();
      ports.reset();
    },
    /** The conversation a send belongs to, or null when the user moved on meanwhile. */
    async ensureSession(titleHint) {
      // A chat being deleted takes no new messages (the server would refuse them), and
      // asking must not count as navigation or it would cancel the reset after the delete.
      if (currentId && deleting.has(currentId)) return null;
      const request = navigation.begin();
      if (currentId) return currentId;
      const pending = (createPending ??= startCreate(titleHint));
      pending.waiters += 1;
      let created;
      try {
        created = await pending.promise;
      } finally {
        pending.waiters -= 1;
      }
      if (!navigation.isCurrent(request)) {
        discardUnused(pending, created);
        return null;
      }
      pending.adopted = true;
      commit(created);
      ports.remember(created);
      refreshSessions();
      return created;
    },
    async load(id) {
      if (ports.isBusy()) return;
      // Choosing the chat already on screen is still the newest intent: it must
      // cancel a slower load of another chat that was requested a moment earlier.
      const request = navigation.begin();
      if (id === currentId) return;
      loadingId = id;
      try {
        const records = await ports.fetchHistory(id);
        if (!navigation.isCurrent(request)) return;
        commit(id);
        ports.remember(id);
        ports.restore(records);
      } catch (error) {
        if (navigation.isCurrent(request)) reportError(error);
      } finally {
        // Cleared even when superseded, or a stale id would later cancel unrelated work.
        if (loadingId === id) loadingId = '';
      }
    },
    async remove(id) {
      // A running turn keeps writing to its chat; tombstoning it underneath would
      // hide a conversation that is still being produced.
      if (id === currentId && ports.isBusy()) return;
      // Deleting the open chat is itself the newest intent; a later open of another
      // chat then outranks the reset. A pending load of the deleted chat is cancelled.
      const request = id === currentId || id === loadingId ? navigation.begin() : null;
      if (id === currentId) deleting.add(id);
      try {
        await ports.deleteSession(id);
        refreshSessions();
        if (request !== null && id === currentId && navigation.isCurrent(request)) {
          ports.forget();
          commit('');
          ports.reset();
        }
      } catch (error) {
        reportError(error);
      } finally {
        deleting.delete(id);
      }
    },
  };
}
