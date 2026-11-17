import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

import { XAI_POLL_MS, isTerminalXaiState, xaiConnectCopy } from '../src/xaiConnect.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('xAI connect states: polling stops only on a terminal state', () => {
  assert.equal(XAI_POLL_MS, 3000);
  for (const state of ['connected', 'denied', 'expired', 'error']) assert.equal(isTerminalXaiState(state), true, state);
  for (const state of ['idle', 'pending', 'starting']) assert.equal(isTerminalXaiState(state), false, state);
});

test('xAI connect copy is short Korean per state and prefers the server message on failure', () => {
  assert.equal(xaiConnectCopy('idle').action, 'xAI 연결');
  assert.equal(xaiConnectCopy('connected').action, '연결 해제');
  assert.match(xaiConnectCopy('pending').title, /코드/);
  assert.match(xaiConnectCopy('denied').title, /거부/);
  assert.match(xaiConnectCopy('expired').title, /만료/);
  assert.equal(xaiConnectCopy('error', '네트워크를 확인하세요.').title, '네트워크를 확인하세요.');
  for (const state of ['idle', 'pending', 'connected', 'denied', 'expired', 'error']) {
    assert.ok(xaiConnectCopy(state).title.length <= 40, `${state} copy stays short`);
  }
});

test('provider panel labels xai and settings wires the connect flow', async () => {
  const panel = await read('../src/ProviderPanel.tsx');
  const settings = await read('../src/SettingsView.tsx');
  const connect = await read('../src/XaiConnectPanel.tsx');
  const api = await read('../src/xaiApi.ts');
  const css = await read('../src/styles/settings.css');
  assert.match(panel, /xai:\s*'xAI \(Grok\)'/);
  assert.match(settings, /<XaiConnect onConnected=\{refreshProviders\}/, 'connect lives in the AI provider card');
  assert.match(connect, /XAI_TITLE_KEYS\[view\.state\]/);
  assert.match(connect, /XAI_ACTION_KEYS\[view\.state\]/);
  assert.match(connect, /t\('xai\.loginFailed'\)/);
  assert.match(connect, /XAI_POLL_MS/);
  assert.match(connect, /isTerminalXaiState/);
  assert.match(settings, /fetchProviders/, 'provider list refreshes after connecting');
  assert.match(connect, /target="_blank"[^>]*rel="noopener noreferrer"|rel="noopener noreferrer"[^>]*target="_blank"/);
  assert.match(connect, /from '\.\/ui\/Button'/, 'uses the shared Button component');
  assert.match(api, /\/api\/providers\/xai\/login\/status/);
  assert.match(api, /\/api\/providers\/xai\/login'/);
  assert.match(api, /\/api\/providers\/xai\/logout/);
  assert.doesNotMatch(api + settings + connect, /access_token|refresh_token|device_code/, 'UI never touches tokens');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.xai-connect[^{]*\{[^}]*min-height:\s*44px/s, 'mobile buttons are at least 44px');
});

test('xai row matches the provider control shape and announces one label', async () => {
  const [connect, button] = await Promise.all([
    read('../src/XaiConnectPanel.tsx'),
    read('../src/ui/Button.tsx'),
  ]);
  assert.match(connect, /variant="secondary"/, 'xai action is a bordered button like the other provider controls');
  assert.doesNotMatch(connect, /quiet/, 'no borderless quiet action in the xai row');
  assert.match(connect, /operation-status/, 'xai state renders through the shared operation-status pattern');
  assert.doesNotMatch(connect, /xai-connect-state/, 'the bare status paragraph is gone');
  assert.doesNotMatch(connect, /xAI \(Grok\) ·/, 'the status line no longer repeats the provider name');
  assert.match(
    button,
    /ui-button-label-measure[^>]*aria-hidden="true"|aria-hidden="true"[^>]*ui-button-label-measure/,
    'the width-reserve measure span stays out of the accessible name',
  );
});
