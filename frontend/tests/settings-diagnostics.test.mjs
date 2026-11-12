import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('diagnostics panel reads preview and creates a bundle', async () => {
  const panel = await read('../src/DiagnosticsPanel.tsx');

  assert.match(panel, /'\/api\/diagnostics'/, 'reads /api/diagnostics for the preview');
  assert.match(panel, /'\/api\/diagnostics\/bundle'/, 'writes the bundle via POST /api/diagnostics/bundle');
  assert.match(panel, /method:\s*'POST'/, 'bundle request uses POST');
});

test('diagnostics panel shows versions, proxy summary, and log count', async () => {
  const panel = await read('../src/DiagnosticsPanel.tsx');

  assert.match(panel, /settings\.diagnosticsAppVersion/, 'shows the app version');
  assert.match(panel, /settings\.diagnosticsOs/, 'shows the operating system');
  assert.match(panel, /settings\.diagnosticsProxy/, 'shows the proxy summary');
  assert.match(panel, /settings\.diagnosticsLogs/, 'shows the log files');
});

test('open-issue button is disabled until the bundle is ready', async () => {
  const panel = await read('../src/DiagnosticsPanel.tsx');

  assert.match(panel, /disabled=\{!bundle\}/, 'open-issue stays disabled before a bundle exists');
  assert.match(panel, /window\.open\(bundle\.issue_url/, 'opens the pre-filled issue URL from the server');
  assert.match(panel, /'noopener,noreferrer'/, 'external open is noopener/noreferrer');
});

test('support section hooks the diagnostics panel into settings', async () => {
  const view = await read('../src/SettingsView.tsx');

  assert.match(view, /DiagnosticsPanel/, 'imports and renders the panel');
  assert.match(view, /section === 'support'/, 'renders under the support section');
  assert.match(view, /'settings\.sectionSupport'/, 'uses the dictionary label');
});

test('diagnostics i18n keys are present in both ko and en', async () => {
  const ko = await read('../src/i18n/ko.ts');
  const en = await read('../src/i18n/en.ts');

  for (const key of [
    'settings.sectionSupport',
    'settings.diagnosticsTitle',
    'settings.diagnosticsIntro',
    'settings.diagnosticsMakeBundle',
    'settings.diagnosticsOpenIssue',
    'settings.diagnosticsBundleReady',
    'settings.diagnosticsBundleFailed',
  ]) {
    assert.match(ko, new RegExp(`'${key.replace(/\./g, '\\.')}'`), `ko has ${key}`);
    assert.match(en, new RegExp(`'${key.replace(/\./g, '\\.')}'`), `en has ${key}`);
  }
});
