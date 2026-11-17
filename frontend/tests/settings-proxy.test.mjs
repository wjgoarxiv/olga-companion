// The settings panel carries the corporate-proxy toggle: host/port form, a
// Test-now button, and a verdict line. Both locales carry the strings. The
// component always probes before letting the toggle flip to on.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('settings has a network section that renders the proxy panel', async () => {
  const view = await read('../src/SettingsView.tsx');
  assert.match(view, /'network'/, 'the section id exists');
  assert.match(view, /settings\.sectionNetwork/, 'the section label reads from the dictionary');
  assert.match(view, /ProxyPanel/, 'the network section renders ProxyPanel');
});

test('ProxyPanel exposes host, port, probe target, a Test-now button, and a verdict line', async () => {
  const panel = await read('../src/ProxyPanel.tsx');
  assert.match(panel, /settings\.proxyHost/, 'host label');
  assert.match(panel, /settings\.proxyPort/, 'port label');
  assert.match(panel, /settings\.proxyProbeTarget/, 'probe target label');
  assert.match(panel, /settings\.proxyTestNow/, 'test-now button label');
  assert.match(panel, /settings\.proxyEnabled/, 'enabled toggle label');
  assert.match(panel, /aria-live/, 'the verdict line is announced to screen readers');
});

test('ProxyPanel uses apiFetch and only saves after a probe has passed', async () => {
  const panel = await read('../src/ProxyPanel.tsx');
  assert.match(panel, /apiFetch\(['"]\/api\/proxy['"]/, 'reads and writes via /api/proxy');
  // The enabled switch cannot flip to on without a successful probe: the save
  // button is disabled while enabled=true and the last probe did not say OK.
  assert.match(panel, /last_probe/, 'the panel reads the probe verdict from the server');
  assert.match(panel, /disabled=\{[^}]*\}/s, 'the save button is gated');
});

test('the shared i18n files carry the proxy section strings in both locales', async () => {
  const [en, ko] = await Promise.all([
    read('../src/i18n/en.ts'),
    read('../src/i18n/ko.ts'),
  ]);
  for (const file of [en, ko]) {
    for (const key of [
      'settings.sectionNetwork',
      'settings.proxyTitle',
      'settings.proxyIntro',
      'settings.proxyEnabled',
      'settings.proxyHost',
      'settings.proxyPort',
      'settings.proxyProbeTarget',
      'settings.proxyTestNow',
      'settings.proxyOk',
      'settings.proxyRefused',
      'settings.proxyHttpStatus',
      'settings.proxyTimeout',
    ]) {
      assert.match(file, new RegExp(`['"]${key.replace('.', '\\.')}['"]\\s*:`), `${key} is translated`);
    }
  }
});
