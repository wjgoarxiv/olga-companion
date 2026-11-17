// A failed tool result carries `error_code`; the card shows a plain sentence for it and
// keeps the English original inside <details>.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { toolErrorText, toolErrorCodeKey } from '../src/toolErrorText.ts';
import { translate } from '../src/i18n/index.ts';

const CODES = [
  'path_not_found',
  'path_outside_workspace',
  'unknown_node',
  'table_unreadable',
  'stale_workspace',
  'approval_unavailable',
  'unit_missing',
];

test('every known code reads as a plain sentence in ko and en, never as the raw label', () => {
  for (const code of CODES) {
    for (const locale of ['ko', 'en']) {
      const text = toolErrorText('Some English original.', locale, code);
      assert.notEqual(text, `toolError.code.${code}`, `${code} ${locale} has no text`);
      assert.doesNotMatch(text, /Some English original|영문 원문/, `${code} ${locale}`);
      assert.doesNotMatch(text, /\{\w+\}/, `${code} ${locale} leaves a placeholder`);
    }
  }
});

test('a missing file and an unknown node keep the quoted name', () => {
  assert.match(toolErrorText("input file not found: 'a.tab'", 'ko', 'path_not_found'), /^파일을 찾을 수 없습니다: 'a\.tab'\./);
  assert.match(toolErrorText("boundaries names node 'N9', which the table does not have.", 'en', 'unknown_node'), /N9/);
});

test('a missing unit reads as a Korean sentence that differs from the English one', () => {
  const ko = toolErrorText('Temperature unit is missing; use one of: K, degC.', 'ko', 'unit_missing');
  const en = toolErrorText('Temperature unit is missing; use one of: K, degC.', 'en', 'unit_missing');
  assert.match(ko, /단위/);
  assert.match(ko, /[가-힣]/);
  assert.notEqual(ko, en);
  assert.equal(toolErrorCodeKey('unit_missing'), 'toolError.code.unit_missing');
});

test('an unknown or missing code falls back to the existing text', () => {
  assert.equal(toolErrorText('Something else.', 'ko', 'brand_new_code'), '도구 오류(영문 원문): Something else.');
  assert.equal(toolErrorText('Something else.', 'ko', undefined), '도구 오류(영문 원문): Something else.');
  assert.equal(toolErrorText("input file not found: 'a.tab'", 'en'), "File not found: 'a.tab'");
  assert.equal(toolErrorCodeKey('brand_new_code'), null);
  assert.equal(toolErrorCodeKey('path_not_found'), 'toolError.code.path_not_found');
});

test('ko and en define the same toolError.code keys', () => {
  for (const code of CODES) {
    assert.notEqual(translate('ko', `toolError.code.${code}`), `toolError.code.${code}`);
    assert.notEqual(translate('en', `toolError.code.${code}`), `toolError.code.${code}`);
  }
});

test('the folded English original is styled square, at least 12px, from tokens only', async () => {
  const css = (await readFile(new URL('../src/styles/chat-tools.css', import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ');
  const rule = (selector) => css.match(new RegExp(`${selector.replace(/[.>]/g, '\\$&')} \\{([^}]*)\\}`))?.[1] ?? '';
  const details = rule('.tool-error-details');
  assert.ok(details, '.tool-error-details has a rule');
  assert.match(details, /font-size: var\(--fs-(?:xs|s|m)\)/, 'font-size comes from a token at or above the 12px floor');
  assert.match(details, /border-radius: 0/);
  assert.match(details, /color: var\(--mute\)/);
  assert.doesNotMatch(css.match(/\.tool-error-details[^{]*\{[^}]*\}/g)?.join(' ') ?? '', /#[0-9a-f]{3,8}\b|rgba?\(/i);
  assert.match(rule('.tool-error-details summary'), /cursor: pointer/);
  assert.match(rule('.tool-error-details p'), /overflow-wrap: anywhere/);
});

test('the card passes the code and folds the English original into details', async () => {
  const card = await readFile(new URL('../src/ToolUnit.tsx', import.meta.url), 'utf8');
  assert.match(card, /error_code/);
  assert.match(card, /<details/);
  assert.match(card, /toolErrorText\(/);
});
