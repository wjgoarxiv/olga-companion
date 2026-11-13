import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const offenders = (dict, pattern) => Object.entries(dict)
  .filter(([, value]) => pattern.test(value))
  .map(([key]) => key);

/* v0.1.4 copy pass: one Korean noun per concept, and no developer words in user-facing text. */

test('ko user strings name the workspace 작업 공간, not the English word', () => {
  assert.equal(ko['settings.workspaceTitle'], '작업 공간 폴더');
  assert.deepEqual(offenders(ko, /workspace|워크스페이스/i), []);
});

test('ko user strings say 공급자, never the English word provider', () => {
  assert.deepEqual(offenders(ko, /provider/i), []);
});

test('the case noun is 사례 in Korean, never 케이스', () => {
  assert.deepEqual(offenders(ko, /케이스/), []);
});

test('users read "local runtime", not the internal word sidecar, in both languages', () => {
  assert.deepEqual(offenders(ko, /sidecar|사이드카/i), []);
  assert.deepEqual(offenders(en, /sidecar/i), []);
  assert.equal(ko['shell.sidecar'], '로컬 런타임');
  assert.equal(en['shell.sidecar'], 'local runtime');
});

test('로컬 런타임 ends in a consonant, so its particles are 이/을/은/과 (the sidecar swap left 가/를)', () => {
  assert.deepEqual(offenders(ko, /로컬 런타임(가|를|는|와)(?![가-힣])/), []);
});

test('the language select has its own plain label while the section title stays bilingual', async () => {
  assert.equal(ko['language.label'], '표시 언어');
  assert.equal(en['language.label'], 'Display language');
  assert.equal(ko['language.title'], '언어 / Language');
  const settings = await read('../src/SettingsView.tsx');
  assert.match(settings, /<h3 className="settings-h">\{t\('language\.title'\)\}<\/h3>/);
  assert.match(settings, /<label htmlFor="ui-language"><span>\{t\('language\.label'\)\}<\/span><\/label>/);
});

test('strings handed over by the tutorial and chat-trust lanes exist in both locales', () => {
  for (const key of ['tutorial.resume', 'chat.retryAskAgain', 'chat.openRunHistory']) {
    assert.equal(typeof ko[key], 'string', `ko ${key}`);
    assert.equal(typeof en[key], 'string', `en ${key}`);
    assert.notEqual(ko[key], en[key], `${key} is translated`);
  }
  assert.ok(ko['tutorial.resume'].includes('{n}') && en['tutorial.resume'].includes('{n}'), 'resume chip keeps its {n} placeholder');
});
