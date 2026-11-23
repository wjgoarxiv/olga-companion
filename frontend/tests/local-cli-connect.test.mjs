import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

import { localCliBillingKey, localCliMessage, localCliView } from '../src/localCliConnect.mjs';
import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const found = { code: 'ok', version: '2.1.220', message_ko: '찾음', message_en: 'Found' };
const result = (code) => ({ code, version: '2.1.220', message_ko: `ko:${code}`, message_en: `en:${code}` });

test('local CLI view: each state has its own title and next step', () => {
  assert.equal(localCliView(null, null).state, 'loading');
  const missing = localCliView(result('not_installed'), null);
  assert.equal(missing.state, 'not_found');
  assert.equal(missing.stepKey, 'localCli.stepInstall');
  assert.equal(missing.showCommand, false);
  assert.equal(localCliView(found, null).titleKey, 'localCli.titleFound');
  assert.equal(localCliView(found, null).stepKey, 'localCli.stepCheck');
  const ready = localCliView(found, result('ok'));
  assert.equal(ready.state, 'ready');
  assert.equal(ready.stepKey, null);
  for (const code of ['not_logged_in', 'login_expired']) {
    const view = localCliView(found, result(code));
    assert.equal(view.state, 'needs_sign_in', code);
    assert.equal(view.stepKey, 'localCli.stepSignIn', code);
    assert.equal(view.showCommand, true, code);
  }
  for (const code of ['rate_limited', 'network', 'timeout', 'crashed', 'unknown']) {
    assert.equal(localCliView(found, result(code)).state, 'problem', code);
  }
});

test('local CLI messages come from the server in the chosen language', () => {
  assert.equal(localCliMessage(result('not_logged_in'), 'ko'), 'ko:not_logged_in');
  assert.equal(localCliMessage(result('not_logged_in'), 'en'), 'en:not_logged_in');
  assert.equal(localCliMessage(null, 'en'), '');
  assert.equal(localCliBillingKey('subscription'), 'localCli.billingSubscription');
  assert.equal(localCliBillingKey('api_key'), 'localCli.billingApiKey');
  assert.equal(localCliBillingKey('unknown'), null);
});

test('every local CLI key exists in both languages and names this PC, not a vendor', () => {
  const keys = Object.keys(ko).filter((key) => key.startsWith('localCli.'));
  assert.ok(keys.length >= 15);
  assert.deepEqual(keys.sort(), Object.keys(en).filter((key) => key.startsWith('localCli.')).sort());
  assert.equal(en['localCli.aria'], 'Local CLI (this PC)');
  assert.equal(ko['localCli.aria'], '이 PC의 로컬 CLI');
  for (const table of [ko, en]) {
    for (const key of ['localCli.aria', 'localCli.titleFound', 'localCli.titleReady']) {
      assert.doesNotMatch(table[key], /anthropic|claude/i, key);
    }
  }
});

test('settings wires the local CLI panel without any credential field', async () => {
  const settings = await read('../src/SettingsView.tsx');
  const panel = await read('../src/LocalCliPanel.tsx');
  const api = await read('../src/localCliApi.ts');
  const provider = await read('../src/ProviderPanel.tsx');
  assert.match(settings, /candidate\.provider === 'claude_cli' && <LocalCliPanel onChanged=\{refreshProviders\}/);
  assert.match(provider, /providerId === 'claude_cli'\) return translate\(locale, 'localCli\.aria'\)/);
  assert.match(api, /\/api\/providers\/claude_cli\/status/);
  assert.match(api, /\/api\/providers\/claude_cli\/check/);
  assert.doesNotMatch(panel, /<input|type="password"|token|apiKey/i, 'the panel never asks for a secret');
  assert.doesNotMatch(panel, /<img|logo/i, 'no vendor logo');
  assert.match(panel, /localCli\.wslNote/);
  assert.match(api, /status\?fresh=1/, 'Find again skips the cached answer');
  assert.match(panel, /refresh\(true\)/);
  assert.match(panel, /fetchLocalCliStatus\(fresh\)/);
});
