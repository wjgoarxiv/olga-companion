import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  CHECK_ON_LAUNCH_KEY,
  clearFoundUpdate,
  peekFoundUpdate,
  readCheckOnLaunch,
  requestOpenUpdates,
  runLaunchCheck,
  subscribeFoundUpdate,
  subscribeOpenUpdates,
  writeCheckOnLaunch,
} from '../src/updateAutoCheck.mjs';

const takeFoundUpdate = () => {
  const update = peekFoundUpdate();
  clearFoundUpdate();
  return update;
};

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => { data.set(key, String(value)); },
  };
}

function fakeUpdate(version) {
  const calls = [];
  return {
    calls,
    update: {
      version,
      download: async () => { calls.push('download'); },
      install: async () => { calls.push('install'); },
      downloadAndInstall: async () => { calls.push('downloadAndInstall'); },
      close: async () => { calls.push('close'); },
    },
  };
}

const noWait = async () => {};

test('checking on launch is on by default and the choice is remembered', () => {
  const storage = memoryStorage();
  assert.equal(readCheckOnLaunch(storage), true);
  writeCheckOnLaunch(storage, false);
  assert.equal(storage.getItem(CHECK_ON_LAUNCH_KEY), 'off');
  assert.equal(readCheckOnLaunch(storage), false);
  writeCheckOnLaunch(storage, true);
  assert.equal(readCheckOnLaunch(storage), true);
});

test('storage that throws reads as on and writing does not throw', () => {
  const broken = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
  assert.equal(readCheckOnLaunch(broken), true);
  assert.doesNotThrow(() => writeCheckOnLaunch(broken, false));
  assert.equal(readCheckOnLaunch(null), true);
});

test('a newer version is reported once, after the delay, and nothing is downloaded or installed', async () => {
  const order = [];
  const { update, calls } = fakeUpdate('0.1.2');
  let checks = 0;
  const outcome = await runLaunchCheck({
    enabled: true,
    delayMs: 8000,
    wait: async (ms) => { order.push(`wait:${ms}`); },
    check: async () => { checks += 1; order.push('check'); return update; },
  });
  assert.deepEqual(outcome, { kind: 'available', version: '0.1.2' });
  assert.equal(checks, 1);
  assert.deepEqual(order, ['wait:8000', 'check']);
  assert.deepEqual(calls, []);
});

test('the found update is handed to Settings once, so it does not check again', async () => {
  const { update } = fakeUpdate('0.1.2');
  await runLaunchCheck({ enabled: true, wait: noWait, check: async () => update });
  assert.equal(takeFoundUpdate(), update);
  assert.equal(takeFoundUpdate(), null);
});

test('reading the found update does not consume it, and a panel that is already open hears about it', async () => {
  clearFoundUpdate();
  const { update } = fakeUpdate('0.1.2');
  const heard = [];
  const unsubscribe = subscribeFoundUpdate(() => heard.push(peekFoundUpdate()));
  await runLaunchCheck({ enabled: true, wait: noWait, check: async () => update });
  assert.equal(peekFoundUpdate(), update);
  assert.equal(peekFoundUpdate(), update, 'a repeated render must see the same handle');
  assert.deepEqual(heard, [update]);
  clearFoundUpdate();
  assert.equal(peekFoundUpdate(), null);
  assert.deepEqual(heard, [update, null]);
  unsubscribe();
});

test('opening Updates from the notice reaches a Settings view that is already open', () => {
  let opened = 0;
  const unsubscribe = subscribeOpenUpdates(() => { opened += 1; });
  requestOpenUpdates();
  assert.equal(opened, 1);
  unsubscribe();
  requestOpenUpdates();
  assert.equal(opened, 1);
});

test('turning the setting off during the delay stops the check', async () => {
  let checked = false;
  let on = true;
  const outcome = await runLaunchCheck({
    enabled: true,
    isEnabled: () => on,
    wait: async () => { on = false; },
    check: async () => { checked = true; return null; },
  });
  assert.deepEqual(outcome, { kind: 'none' });
  assert.equal(checked, false);
});

test('no update, an error, or a missing desktop shell stays silent', async () => {
  assert.deepEqual(await runLaunchCheck({ enabled: true, wait: noWait, check: async () => null }), { kind: 'none' });
  assert.deepEqual(
    await runLaunchCheck({ enabled: true, wait: noWait, check: async () => { throw new Error('404 Not Found'); } }),
    { kind: 'none' },
  );
  assert.deepEqual(
    await runLaunchCheck({ enabled: true, wait: noWait, check: async () => { throw new TypeError('window.__TAURI_INTERNALS__ is undefined'); } }),
    { kind: 'none' },
  );
  assert.equal(takeFoundUpdate(), null);
});

test('with the setting off there is no wait and no check', async () => {
  let touched = false;
  const outcome = await runLaunchCheck({
    enabled: false,
    wait: async () => { touched = true; },
    check: async () => { touched = true; return null; },
  });
  assert.deepEqual(outcome, { kind: 'none' });
  assert.equal(touched, false);
});

test('a check that resolves after the app gave up is closed and not reported', async () => {
  const { update, calls } = fakeUpdate('0.1.2');
  let checked = false;
  const outcome = await runLaunchCheck({
    enabled: true,
    wait: noWait,
    check: async () => { checked = true; return update; },
    isCancelled: () => checked,
  });
  assert.deepEqual(outcome, { kind: 'none' });
  assert.deepEqual(calls, ['close']);
  assert.equal(takeFoundUpdate(), null);
});

test('the app shell wires the launch check and the notice only opens Settings → Updates', () => {
  const bar = readFileSync(new URL('../src/shell/StatusBar.tsx', import.meta.url), 'utf8');
  assert.match(bar, /<UpdateNotice onOpenSettings=/);
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /onOpenUpdates=\{\(\) => selectView\('settings'\)\}/);
  const hook = readFileSync(new URL('../src/useLaunchUpdateCheck.ts', import.meta.url), 'utf8');
  assert.match(hook, /runLaunchCheck\(/);
  const notice = readFileSync(new URL('../src/UpdateNotice.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(notice, /\.download\(|\.install\(|downloadAndInstall|plugin-updater/);
  const panel = readFileSync(new URL('../src/UpdatePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /useSyncExternalStore\(subscribeFoundUpdate, peekFoundUpdate\)/);
  assert.doesNotMatch(panel, /takeFoundUpdate/);
  assert.match(panel, /writeCheckOnLaunch\(/);
  const settings = readFileSync(new URL('../src/SettingsView.tsx', import.meta.url), 'utf8');
  assert.match(settings, /subscribeOpenUpdates\(/);
  assert.match(notice, /requestOpenUpdates\(\)/);
  assert.match(hook, /isEnabled: \(\) => readCheckOnLaunch\(browserStorage\(\)\)/);
  assert.match(hook, /clearTimeout/);
});

test('the notice keeps one live region mounted so screen readers announce it', () => {
  const notice = readFileSync(new URL('../src/UpdateNotice.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(notice, /if \(!version\) return null/);
  assert.match(notice, /<div className="update-notice-live" role="status" aria-live="polite">/);
});

test('the Korean notice reads naturally, without a particle placeholder', () => {
  const ko = readFileSync(new URL('../src/i18n/ko.ts', import.meta.url), 'utf8');
  const line = ko.split('\n').find((l) => l.includes("'update.notice':"));
  assert.ok(line);
  assert.doesNotMatch(line, /\(를\)|\(을\)/);
});

test('every new string exists in both languages', () => {
  const en = readFileSync(new URL('../src/i18n/en.ts', import.meta.url), 'utf8');
  const ko = readFileSync(new URL('../src/i18n/ko.ts', import.meta.url), 'utf8');
  for (const key of ['update.checkOnLaunch', 'update.notice', 'update.noticeOpen', 'update.noticeDismiss']) {
    assert.match(en, new RegExp(`'${key.replace('.', '\\.')}':`), `en ${key}`);
    assert.match(ko, new RegExp(`'${key.replace('.', '\\.')}':`), `ko ${key}`);
  }
});
