// N7: the glossary keeps the OLGA keyword in English and gives its meaning in the UI language.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { entryMeaning, findEntry } from '../src/glossary.ts';

const entries = JSON.parse(await readFile(new URL('../../src/olga_companion/resources/olga_glossary.json', import.meta.url), 'utf8'));
const HANGUL = /[가-힣]/;

test('every entry has an English and a Korean meaning', () => {
  assert.ok(entries.length >= 90);
  for (const entry of entries) {
    assert.ok(entry.meaning_en && !HANGUL.test(entry.meaning_en), `${entry.term} en`);
    assert.ok(entry.meaning_ko && HANGUL.test(entry.meaning_ko), `${entry.term} ko`);
  }
});

test('the popup words follow the locale; the term stays in English', () => {
  const pt = findEntry(entries, 'pt');
  assert.equal(pt.term, 'PT');
  assert.equal(entryMeaning(pt, 'en'), 'Pressure');
  assert.equal(entryMeaning(pt, 'ko'), '압력');
});

test('a meaning is a meaning, not a check rule', () => {
  for (const term of ['NODE', 'INLET', 'OUTLET', 'FLOWPATH', 'TERMINALS', 'NETWORKCOMPONENT']) {
    assert.doesNotMatch(entryMeaning(findEntry(entries, term), 'en'), /^(Check|Every|Each)\b/, term);
  }
});

test('an older entry with only one meaning still shows it', () => {
  assert.equal(entryMeaning({ term: 'X', kind: 'keyword', meaning: 'Old words', source: { file: 'f', line: 1 } }, 'ko'), 'Old words');
});
