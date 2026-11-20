import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('provider types carry connection state for the rebuild', async () => {
  const types = await read('../src/types.ts');
  assert.match(types, /connected\?:\s*boolean/, 'ProviderInfo exposes optional connected');
  assert.match(types, /login\?:\s*'xai_device'\s*\|\s*'apikey'\s*\|\s*'external'/, 'ProviderInfo exposes the login kind');
});

test('provider panel labels every select in Korean', async () => {
  const [panel, ko] = await Promise.all([
    read('../src/ProviderPanel.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(panel, /label=\{t\('provider\.provider'\)\}/, 'provider select has a visible 공급자 label');
  assert.match(panel, /controlId="provider-select"/, 'labels are tied to their selects');
  assert.match(panel, /label=\{t\('provider\.effort'\)\}/, 'effort select is labeled 추론 수준');
  assert.match(panel, /t\('provider\.connection'\)/, 'apikey model select is labeled 연결');
  assert.match(ko, /'provider\.provider': '공급자'/, 'ko provider label is exact');
  assert.match(ko, /'provider\.effort': '추론 수준'/, 'ko effort label is exact');
});

test('provider options disable unconnected providers in Korean, keeping the selection visible', async () => {
  const [panel, ko] = await Promise.all([
    read('../src/ProviderPanel.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(panel, /t\('provider\.notConnectedSuffix'\)/, 'unconnected suffix reads from the dictionary');
  assert.match(ko, /'provider\.notConnectedSuffix': ' — 연결 안 됨'/, 'unconnected suffix is Korean');
  assert.match(panel, /connected/, 'disabled state derives from connected');
  assert.match(panel, /has_catalog/, 'missing connected falls back to has_catalog');
  assert.match(panel, /OpenAI \(Codex\)/, 'OpenAI keeps its Korean operator label');
  assert.match(panel, /GitHub Copilot/, 'Copilot keeps its Korean operator label');
  assert.match(panel, /Antigravity \(Gemini\)/, 'Antigravity keeps its Korean operator label');
  assert.match(panel, /xAI \(Grok\)/, 'xAI keeps its Korean operator label');
  assert.match(panel, /API 키/, 'apikey keeps its Korean operator label');
  assert.doesNotMatch(panel, /not connected/, 'no English not-connected copy remains');
});

test('provider panel shows one inline notice instead of a model select when disconnected', async () => {
  const [panel, ko] = await Promise.all([
    read('../src/ProviderPanel.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(panel, /t\('provider\.disconnectedNotice'\)/, 'selected-but-disconnected notice reads from the dictionary');
  assert.match(
    ko,
    /이 공급자는 연결되어 있지 않습니다\. 연결된 공급자를 고르거나 아래 '계정 연결'에서 연결하세요\./,
    'selected-but-disconnected notice is exact',
  );
});

test('settings groups one account row per provider with the xAI device flow inside its row', async () => {
  const [settings, ko] = await Promise.all([
    read('../src/SettingsView.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(settings, /t\('settings\.accounts'\)/, 'account section exists below the selects');
  assert.match(ko, /'settings\.accounts': '계정 연결'/, 'ko account heading is exact');
  assert.match(settings, /<XaiConnect onConnected=\{refreshProviders\}/, 'providers refresh after xAI connects');
  assert.match(settings, /onChanged=\{refreshProviders\}/, 'providers refresh after API-key changes');
  assert.match(settings, /t\('settings\.connected'\)/, 'connected status copy exists');
  assert.match(settings, /t\('settings\.disconnected'\)/, 'disconnected status copy exists');
  assert.match(settings, /t\(hint\)/, 'account hints resolve through the dictionary');
  assert.match(ko, /'API 키 연결' 카드에서/, 'apikey row uses the neutral card wording');
  assert.match(ko, /이 앱에서는 아직 직접 연결할 수 없습니다\./, 'external rows explain direct connect is unavailable');
});

test('status bar names the disconnected provider state in Korean', async () => {
  const [app, ko] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(app, /t\('status\.disconnected'\)/, 'status bar reads 연결 안 됨 from the dictionary');
  assert.match(ko, /'status\.disconnected': '연결 안 됨'/, 'ko disconnected copy is exact');
  assert.doesNotMatch(app, /: '연결 안 됨'|Not connected/, 'no hardcoded fallback remains in the status bar');
});

test('xai row does not repeat the idle sentence; other states and the device code stay', async () => {
  const connect = await read('../src/XaiConnectPanel.tsx');
  assert.match(connect, /view\.state !== 'idle'/, 'the idle title is gated out inside the row');
  assert.match(connect, /operation-status/, 'pending/error/connected messages still render');
  assert.match(connect, /xai-connect-code/, 'the device code still renders while pending');
});
