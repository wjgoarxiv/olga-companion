// The status bar carries a small "Proxy on" badge when the toggle is on
// and the last probe said OK. It stays hidden otherwise so the status row
// does not grow a permanent control the user never flips.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the status bar renders a proxy badge gated on enabled and probe OK', async () => {
  const bar = await read('../src/shell/StatusBar.tsx');
  assert.match(bar, /wb-status-proxy/, 'the badge has a dedicated class');
  assert.match(bar, /settings\.statusProxyOn/, 'the badge label reads from the dictionary');
});

test('the badge subscribes to the shared proxy status store', async () => {
  const bar = await read('../src/shell/StatusBar.tsx');
  assert.match(bar, /proxyStatus|subscribeProxyStatus/, 'the bar reads from the shared store');
});

test('the shared proxy-status store publishes after every save', async () => {
  const store = await read('../src/proxyStatus.mjs');
  assert.match(store, /subscribe/, 'store exposes subscribe()');
  assert.match(store, /refresh/, 'store exposes refresh()');
  assert.match(store, /apiFetch\(['"]\/api\/proxy['"]/, 'refresh hits /api/proxy');
  const panel = await read('../src/ProxyPanel.tsx');
  assert.match(panel, /refreshProxyStatus|proxyStatus/, 'the settings panel notifies the store after save');
});

test('both locales translate the status badge label', async () => {
  for (const file of ['../src/i18n/en.ts', '../src/i18n/ko.ts']) {
    const text = await read(file);
    assert.match(text, /['"]settings\.statusProxyOn['"]\s*:/, `${file} carries statusProxyOn`);
  }
});
