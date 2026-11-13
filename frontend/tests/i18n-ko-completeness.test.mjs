import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* Todo 13: ko==en means untranslated UI copy. The allow-list is only for
 * values identical by construction (identifiers, keywords, codes, units,
 * file names, unit templates, autonyms) — every entry must carry a reason. */

test('ko dictionary carries no untranslated English outside the allow-list', async () => {
  const allow = JSON.parse(await read('../i18n-same-value-allowlist.json'));
  assert.ok(allow && typeof allow.allow === 'object', 'the same-value allow-list has an allow map');

  const unlisted = [];
  for (const key of Object.keys(ko)) {
    if (en[key] === undefined) continue;
    if (ko[key] === en[key] && !(key in allow.allow)) unlisted.push(key);
  }
  assert.deepEqual(unlisted, [], `ko==en outside the allow-list: ${unlisted.join(', ')}`);
});

test('every same-value allow-list entry carries a reason and still applies', async () => {
  const allow = JSON.parse(await read('../i18n-same-value-allowlist.json'));

  for (const [key, reason] of Object.entries(allow.allow)) {
    assert.equal(typeof reason, 'string', `${key} needs a string reason`);
    assert.ok(reason.trim().length > 0, `${key} needs a non-empty reason`);
    assert.ok(key in ko, `${key} must exist in ko (remove stale entries)`);
    assert.ok(key in en, `${key} must exist in en (remove stale entries)`);
    assert.equal(ko[key], en[key], `${key} is translated now — remove it from the allow-list`);
  }
});
