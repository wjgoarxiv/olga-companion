// R15: solver findings follow the UI language instead of always showing Korean.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const panel = await readFile(new URL('../src/RunFailurePanel.tsx', import.meta.url), 'utf8');
const en = await readFile(new URL('../src/i18n/en.ts', import.meta.url), 'utf8');
const ko = await readFile(new URL('../src/i18n/ko.ts', import.meta.url), 'utf8');
const CODES = ['DTMIN_HIT', 'NEGATIVE_HOLDUP', 'NAN_VALUE', 'STALLED', 'MASS_ERROR'];

test('the panel translates a finding by its code', () => {
  assert.match(panel, /findingMessage\(t, finding\.code, finding\.message\)/);
  assert.doesNotMatch(panel, /<code>\{finding\.code\}<\/code> \{finding\.message\}/);
});

test('every solver finding code has English and Korean text', () => {
  for (const code of CODES) {
    const enLine = en.match(new RegExp(`'run\\.finding\\.${code}': '([^']+)'`));
    const koLine = ko.match(new RegExp(`'run\\.finding\\.${code}': '([^']+)'`));
    assert.ok(enLine && koLine, code);
    assert.doesNotMatch(enLine[1], /[가-힣]/, `${code} English text has no Hangul`);
    assert.match(koLine[1], /[가-힣]/, `${code} Korean text is Korean`);
  }
});
