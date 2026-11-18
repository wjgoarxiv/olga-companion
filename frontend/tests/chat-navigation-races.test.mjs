import assert from 'node:assert/strict';
import test from 'node:test';
import { createChatNavigator } from '../src/chatNavigation.mjs';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function harness(overrides = {}) {
  const state = { id: '', sessions: [], restored: [], resets: 0, remembered: [], forgotten: 0, errors: [], busy: false, created: 0 };
  const ports = {
    bootstrap: async () => ({ sessionId: '', sessions: [], records: [] }),
    commit: (id) => { state.id = id; },
    createSession: async () => { state.created += 1; return `created-${state.created}`; },
    deleteSession: async () => ({ deleted: true }),
    error: (error) => state.errors.push(error.message),
    fetchHistory: async (id) => [{ record: 'user', text: `history ${id}` }],
    fetchSessions: async () => [],
    forget: () => { state.forgotten += 1; },
    isBusy: () => state.busy,
    remember: (id) => state.remembered.push(id),
    reset: () => { state.resets += 1; },
    restore: (records) => state.restored.push(records[0]?.text ?? ''),
    setSessions: (items) => { state.sessions = [...items]; },
    ...overrides,
  };
  return { state, navigator: createChatNavigator(ports) };
}

test('rapid A then B load keeps B even when A resolves last', async () => {
  const history = { A: deferred(), B: deferred() };
  const { state, navigator } = harness({ fetchHistory: (id) => history[id].promise });

  const a = navigator.load('A');
  const b = navigator.load('B');
  history.B.resolve([{ text: 'B' }]);
  await b;
  history.A.resolve([{ text: 'A' }]);
  await a;

  assert.equal(state.id, 'B');
  assert.deepEqual(state.restored, ['B']);
  assert.deepEqual(state.remembered, ['B']);
});

test('a late failure of an abandoned load is not shown on the current chat', async () => {
  const slow = deferred();
  const { state, navigator } = harness({ fetchHistory: (id) => (id === 'A' ? slow.promise : Promise.resolve([{ text: id }])) });

  const a = navigator.load('A');
  await navigator.load('B');
  slow.reject(new Error('A is gone'));
  await a;

  assert.equal(state.id, 'B');
  assert.deepEqual(state.errors, []);
});

test('new chat during a pending load discards the old response', async () => {
  const pending = deferred();
  const { state, navigator } = harness({ fetchHistory: () => pending.promise });

  const load = navigator.load('A');
  navigator.newChat();
  pending.resolve([{ text: 'A' }]);
  await load;

  assert.equal(state.id, '');
  assert.deepEqual(state.restored, []);
  assert.equal(state.resets, 1);
});

test('initial restore is dropped when the user starts a new chat first', async () => {
  const boot = deferred();
  const { state, navigator } = harness({ bootstrap: () => boot.promise });

  const initial = navigator.startInitial();
  navigator.newChat();
  boot.resolve({ sessionId: 'old', sessions: [{ session_id: 'old', title: 'x' }], records: [{ text: 'old' }] });
  await initial;

  assert.equal(state.id, '');
  assert.deepEqual(state.restored, []);
  assert.deepEqual(state.sessions.map((item) => item.session_id), ['old'], 'the saved-chat list is still valid and stays');
});

test('a session created for a send is discarded when the user opened another chat', async () => {
  const created = deferred();
  const { state, navigator } = harness({ createSession: () => created.promise });

  const send = navigator.ensureSession();
  await navigator.load('B');
  created.resolve('late-new');

  assert.equal(await send, null);
  assert.equal(state.id, 'B');
});

test('an existing conversation is returned and invalidates a pending load', async () => {
  const pending = deferred();
  const { state, navigator } = harness({
    fetchHistory: (id) => (id === 'B' ? pending.promise : Promise.resolve([{ text: id }])),
  });
  await navigator.load('A');

  const slowLoad = navigator.load('B');
  const target = await navigator.ensureSession();
  pending.resolve([{ text: 'B' }]);
  await slowLoad;

  assert.equal(target, 'A');
  assert.equal(state.id, 'A');
});

test('deleting a chat that is no longer current never resets the active chat', async () => {
  const removal = deferred();
  const { state, navigator } = harness({ deleteSession: () => removal.promise });
  await navigator.load('A');

  const deleting = navigator.remove('A');
  await navigator.load('B');
  removal.resolve({ deleted: true });
  await deleting;

  assert.equal(state.id, 'B');
  assert.equal(state.resets, 0);
});

test('deleting the current chat clears it and out-of-order list refreshes keep the newest', async () => {
  const lists = [deferred(), deferred()];
  let call = 0;
  const { state, navigator } = harness({ fetchSessions: () => lists[call++].promise });
  await navigator.load('A');

  await navigator.remove('A');
  await navigator.remove('missing');
  lists[1].resolve([{ session_id: 'new', title: 'newest' }]);
  lists[0].resolve([{ session_id: 'old', title: 'stale' }]);
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(state.id, '');
  assert.equal(state.resets, 1);
  assert.deepEqual(state.sessions.map((item) => item.session_id), ['new']);
});

test('busy streams block load and new chat', async () => {
  const { state, navigator } = harness();
  state.busy = true;

  await navigator.load('A');
  navigator.newChat();

  assert.equal(state.id, '');
  assert.deepEqual(state.restored, []);
  assert.equal(state.resets, 0);
});

test('creation failure leaves no conversation and can be retried', async () => {
  let attempts = 0;
  const { state, navigator } = harness({
    createSession: async () => { attempts += 1; if (attempts === 1) throw new Error('offline'); return 'created'; },
  });

  await assert.rejects(navigator.ensureSession(), /offline/);
  assert.equal(await navigator.ensureSession(), 'created');
  assert.equal(state.id, 'created');
});

test('a new conversation is titled by its first question, not by a shared placeholder', async () => {
  const { chatTitle } = await import('../src/chatNavigation.mjs');
  const titles = [];
  const { navigator } = harness({ createSession: async (title) => { titles.push(title); return 'created'; } });

  await navigator.ensureSession('  배관의   압력 변화를\n확인하고 싶습니다  ');

  assert.deepEqual(titles, ['배관의 압력 변화를 확인하고 싶습니다']);
  assert.equal(chatTitle(''), 'OLGA session');
  assert.equal(chatTitle(undefined), 'OLGA session');
  assert.equal([...chatTitle('가'.repeat(100))].length, 48);
  assert.match(chatTitle('가'.repeat(100)), /…$/u);
});

test('re-selecting the chat on screen cancels a slower load of another chat', async () => {
  const slow = deferred();
  const { state, navigator } = harness({
    fetchHistory: (id) => (id === 'A' ? slow.promise : Promise.resolve([{ text: id }])),
  });
  await navigator.load('B');

  const loadA = navigator.load('A');
  await navigator.load('B');
  slow.resolve([{ text: 'A' }]);
  await loadA;

  assert.equal(state.id, 'B');
  assert.deepEqual(state.restored, ['B']);
});

test('deleting the open chat does not undo a newer open of another chat', async () => {
  const removal = deferred();
  const history = { B: deferred() };
  const { state, navigator } = harness({
    deleteSession: () => removal.promise,
    fetchHistory: (id) => (id === 'B' ? history.B.promise : Promise.resolve([{ text: id }])),
  });
  await navigator.load('A');

  const deleting = navigator.remove('A');
  const opening = navigator.load('B');
  removal.resolve({ deleted: true });
  await deleting;
  history.B.resolve([{ text: 'B' }]);
  await opening;

  assert.equal(state.id, 'B', 'the newest intent (open B) outranks the reset from deleting A');
  assert.equal(state.resets, 0);
});

test('deleting a chat whose load is in flight cancels that load', async () => {
  const slow = deferred();
  const { state, navigator } = harness({
    fetchHistory: (id) => (id === 'X' ? slow.promise : Promise.resolve([{ text: id }])),
  });
  await navigator.load('A');

  const loading = navigator.load('X');
  await navigator.remove('X');
  slow.resolve([{ text: 'X' }]);
  await loading;

  assert.equal(state.id, 'A', 'a deleted chat can never be opened by its late response');
});

test('a conversation created for a send the user abandoned is discarded, not left as an empty chat', async () => {
  const creating = deferred();
  const deleted = [];
  const { state, navigator } = harness({
    createSession: () => creating.promise,
    deleteSession: async (id) => { deleted.push(id); return { deleted: true }; },
  });

  const send = navigator.ensureSession('first question');
  await navigator.load('B'); // the user opens another chat while the create is in flight
  creating.resolve('ghost-1');

  assert.equal(await send, null);
  await Promise.resolve();
  assert.deepEqual(deleted, ['ghost-1']);
  assert.equal(state.id, 'B');
});

test('a double send shares one create: the winner keeps it and nothing is discarded', async () => {
  const creating = deferred();
  const deleted = [];
  const { state, navigator } = harness({
    createSession: () => creating.promise,
    deleteSession: async (id) => { deleted.push(id); return { deleted: true }; },
  });

  const first = navigator.ensureSession('q');
  const second = navigator.ensureSession('q');
  creating.resolve('shared-1');

  assert.equal(await first, null); // superseded by the newer send
  assert.equal(await second, 'shared-1');
  assert.deepEqual(deleted, []);
  assert.equal(state.id, 'shared-1');
});

test('two abandoned sends sharing one create discard it exactly once', async () => {
  const creating = deferred();
  const deleted = [];
  const { navigator } = harness({
    createSession: () => creating.promise,
    deleteSession: async (id) => { deleted.push(id); return { deleted: true }; },
  });

  const first = navigator.ensureSession('q');
  const second = navigator.ensureSession('q');
  navigator.newChat();
  const third = navigator.ensureSession('later'); // a newer intent that has its own create
  creating.resolve('shared-2');
  await Promise.all([first, second]);
  await Promise.resolve();

  assert.deepEqual(deleted, ['shared-2']);
  void third;
});

test('the open chat cannot be deleted while its turn is running', async () => {
  const deleted = [];
  const { state, navigator } = harness({ deleteSession: async (id) => { deleted.push(id); return {}; } });
  await navigator.load('A');
  state.busy = true;

  await navigator.remove('A');

  assert.deepEqual(deleted, []);
  assert.equal(state.id, 'A');
  assert.equal(state.resets, 0);
});

test('another chat can still be deleted while a turn is running', async () => {
  const deleted = [];
  const { state, navigator } = harness({ deleteSession: async (id) => { deleted.push(id); return {}; } });
  await navigator.load('A');
  state.busy = true;

  await navigator.remove('B');

  assert.deepEqual(deleted, ['B']);
  assert.equal(state.id, 'A');
});

test('a send that starts while the open chat is being deleted never reaches the deleted chat', async () => {
  const deleting = deferred();
  const { state, navigator } = harness({ deleteSession: () => deleting.promise });
  await navigator.load('A');

  const removal = navigator.remove('A');
  const send = await navigator.ensureSession('too late');
  deleting.resolve({ deleted: true });
  await removal;

  assert.equal(send, null);
  assert.equal(state.id, '');
  assert.equal(state.resets, 1);
});

test('deleting another chat is not cancelled or confused by an earlier superseded load', async () => {
  const history = deferred();
  const creating = deferred();
  const { state, navigator } = harness({
    fetchHistory: () => history.promise,
    createSession: () => creating.promise,
  });

  const load = navigator.load('B'); // superseded below, but its request is still in flight
  const send = navigator.ensureSession('first question');
  history.resolve([{ text: 'late B' }]);
  await load;
  const removal = navigator.remove('B'); // an unrelated delete of the abandoned id
  creating.resolve('created-1');

  assert.equal(await send, 'created-1');
  await removal;
  assert.equal(state.id, 'created-1');
});
