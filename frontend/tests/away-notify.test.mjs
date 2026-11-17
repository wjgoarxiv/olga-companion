import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

const away = await import('../src/awayNotify.mjs');

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function storage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => { data.set(key, String(value)); },
  };
}

test('T8: no away notification while the window is focused and visible', () => {
  assert.equal(away.shouldNotifyAway({ hidden: false, focused: true, enabled: true }), false);
});

test('T8: away notification fires when hidden or unfocused, unless disabled', () => {
  assert.equal(away.shouldNotifyAway({ hidden: true, focused: true, enabled: true }), true);
  assert.equal(away.shouldNotifyAway({ hidden: false, focused: false, enabled: true }), true);
  assert.equal(away.shouldNotifyAway({ hidden: true, focused: false, enabled: false }), false);
});

test('T8: same-kind events collapse within 5 s, separate kinds stay separate', () => {
  let now = 1_000;
  const queue = away.createAwayCollapse({ now: () => now });
  const first = queue.push('run-finished');
  assert.equal(first.collapsed, false);
  now += 4_999;
  const second = queue.push('run-finished');
  assert.equal(second.collapsed, true);
  assert.equal(second.count, 2);
  const other = queue.push('approval-needed');
  assert.equal(other.collapsed, false);
  now += 5_000;
  const later = queue.push('run-finished');
  assert.equal(later.collapsed, false);
  assert.equal(later.count, 1);
});

test('T8: the away toggle defaults to on and persists off', () => {
  assert.equal(away.readAwayNotifyEnabled(storage()), true);
  const store = storage();
  away.writeAwayNotifyEnabled(store, false);
  assert.equal(away.readAwayNotifyEnabled(store), false);
  away.writeAwayNotifyEnabled(store, true);
  assert.equal(away.readAwayNotifyEnabled(store), true);
});

function patrolItem(runId, state) {
  return {
    kind: 'tool', id: `t-${runId}`, name: 'run_patrol', callId: 'c',
    status: 'done', result: { terminal: true, run_id: runId, state },
  };
}

test('T8: only new terminal runs notify, restored history seeds silently', () => {
  const seen = new Set();
  const restored = away.newTerminalRuns([patrolItem('r1', 'completed'), patrolItem('r2', 'failed')], seen);
  assert.deepEqual(restored.map((r) => r.runId).sort(), ['r1', 'r2']);
  assert.ok(seen.has('r1') && seen.has('r2'));
  assert.deepEqual(away.newTerminalRuns([patrolItem('r1', 'completed')], seen), [], 'already seen never refires');
  const fresh = away.newTerminalRuns([patrolItem('r1', 'completed'), patrolItem('r3', 'completed')], seen);
  assert.deepEqual(fresh.map((r) => r.runId), ['r3']);
  assert.equal(away.newTerminalRuns([{ kind: 'user', id: 'u', text: 'hi' }], seen).length, 0);
});

test('T8: a chat-done right after a run finish collapses into the run notification', () => {
  assert.equal(away.shouldSuppressChatDone({ lastRunNotifiedAt: 1000, now: 1000 + 4999 }), true);
  assert.equal(away.shouldSuppressChatDone({ lastRunNotifiedAt: 1000, now: 1000 + 5000 }), false);
  assert.equal(away.shouldSuppressChatDone({ lastRunNotifiedAt: null, now: 2000 }), false);
});

test('T8: delivery fans out to toast plus taskbar behind one function', async () => {
  const calls = [];
  const deliver = away.createAwayNotifier({
    showToast: (entry) => { calls.push(['toast', entry.kind]); },
    flashTaskbar: () => { calls.push(['flash']); },
  });
  await deliver({ kind: 'approval-needed', title: 't', body: 'b' });
  assert.deepEqual(calls, [['toast', 'approval-needed'], ['flash']]);
});

test('T8: away copy exists in ko and en', () => {
  for (const key of [
    'settings.notifyAway', 'settings.notifyAwayNote',
    'notify.runFinished', 'notify.runFailed', 'notify.approvalNeeded',
    'notify.chatDone', 'notify.updateReady', 'notify.dismiss',
  ]) {
    assert.ok(ko[key], `ko ${key}`);
    assert.ok(en[key], `en ${key}`);
    assert.notEqual(ko[key], en[key], `${key} is translated`);
  }
});

test('T8: toast queue is aria-live with auto-dismiss, taskbar uses no new dependency', async () => {
  const [toast, hook, awaySrc, setting, settings, pkg, css] = await Promise.all([
    read('../src/ui/Toast.tsx'),
    read('../src/useAwayNotify.ts'),
    read('../src/awayNotify.mjs'),
    read('../src/AwayNotifySetting.tsx'),
    read('../src/SettingsView.tsx'),
    read('../../package.json'),
    read('../src/styles/boot.css'),
  ]);
  assert.match(toast, /aria-live/, 'toasts announce to assistive tech');
  assert.match(toast, /setTimeout/, 'toasts auto-dismiss');
  assert.match(css, /toast-slide-in/, 'toasts slide in');
  assert.match(css, /prefers-reduced-motion/, 'toast motion collapses under reduced motion');
  assert.match(toast, /notify\.dismiss/, 'toast close label comes from i18n');
  assert.match(awaySrc, /requestUserAttention/, 'taskbar flash goes through the window API');
  assert.match(awaySrc, /@tauri-apps\/api\/window/, 'flash uses the installed window API');
  assert.match(hook, /document\.hidden/, 'delivery checks visibility, not a timer guess');
  assert.match(setting, /settings\.notifyAway/, 'the toggle carries the i18n copy');
  assert.match(settings, /AwayNotifySetting/, 'Settings mounts the toggle component');
  assert.match(toast, /hasFocus/, 'away toasts wait for focus instead of vanishing unseen');
  assert.match(hook, /hasFocus/, 'focus tracking starts from the real window state');
  assert.doesNotMatch(pkg, /tauri-plugin-notification/, 'fallback adds no OS-toast dependency');
  for (const kind of ['run-finished', 'run-failed', 'approval-needed', 'chat-done', 'update-ready']) {
    assert.match(hook, new RegExp(kind), `hook wires ${kind}`);
  }
});
