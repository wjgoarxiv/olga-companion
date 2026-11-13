import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('saved keys leave React state immediately and never leak', async () => {
  const [component, api] = await Promise.all([
    read('../src/ApiKeyConnections.tsx'),
    read('../src/apiKeyApi.ts'),
  ]);
  assert.match(component, /setKey\(['"]{2}\)/, 'the key input is cleared right after save');
  assert.doesNotMatch(component + api, /localStorage/, 'no key material in web storage');
  assert.doesNotMatch(component + api, /console\.(log|info|debug|warn|error)/, 'no key material in logs');
  assert.doesNotMatch(api, /key.*\}.*\$\{|GET.*key/i, 'no route ever returns the key');
});

test('every outcome maps to the contract recovery sentence', async () => {
  const { outcomeSentence } = await import('../src/apiKeyOutcomes.ts');
  const cases = {
    saved: '저장했습니다.',
    verified: '연결이 확인됐습니다.',
    insecure_scheme: 'https 주소만 저장할 수 있습니다(내 컴퓨터 주소 제외).',
    unauthorized: '키가 거절되었습니다.',
    unreachable: '주소에 연결하지 못했습니다.',
    rate_limited: '요청 한도에 걸렸습니다.',
  };
  for (const [outcome, fragment] of Object.entries(cases)) {
    assert.ok(outcomeSentence(outcome).includes(fragment), outcome);
  }
  assert.match(outcomeSentence('not_found'), /주소를 확인하세요/);
  assert.match(outcomeSentence('invalid_base_url'), /주소를 확인하세요/);
  assert.equal(
    outcomeSentence('request_rejected'),
    '요청이 거절됐습니다. 기본 주소와 모델 이름을 확인하세요.',
  );
  assert.doesNotMatch(outcomeSentence('unauthorized', 'sk-CANARY-123'), /CANARY/, 'sentences never echo input');
});

test('delete needs an in-app confirm step and fields ship with no defaults', async () => {
  const [component, panel, settings] = await Promise.all([
    read('../src/ApiKeyConnections.tsx'),
    read('../src/ProviderPanel.tsx'),
    read('../src/SettingsView.tsx'),
  ]);
  assert.doesNotMatch(component, /window\.confirm/, 'delete confirms inside the app');
  assert.match(component, /t\('apikey\.deleteConfirm'\)/, 'delete is a two-step action');
  assert.match(component, /useState\(''\)/, 'text fields start empty');
  assert.doesNotMatch(component, /useState\('https?:/, 'base URL has no default value');
  assert.match(component, /autoComplete="off"/, 'the key field disables completion');
  assert.match(component, /spellCheck={false}/, 'the key field disables spellcheck');
  assert.match(panel, /apikey/, 'verified API-key connections appear in the provider list');
  assert.match(settings, /ApiKeyConnections/, 'settings hosts the API key card');
});
