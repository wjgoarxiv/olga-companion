import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('proxy setting is titled as a plain on/off switch in both locales', async () => {
  const ko = await read('../src/i18n/ko.ts');
  const en = await read('../src/i18n/en.ts');

  assert.match(ko, /'settings\.proxyTitle': '프록시 켜기\/끄기'/);
  assert.match(en, /'settings\.proxyTitle': 'Proxy on\/off'/);
});

test('no UI string calls it a company or external-network proxy', async () => {
  const ko = await read('../src/i18n/ko.ts');
  const en = await read('../src/i18n/en.ts');

  assert.doesNotMatch(ko, /사외망 프록시|회사 프록시/);
  assert.doesNotMatch(en, /External proxy|corporate proxy/i);
});
