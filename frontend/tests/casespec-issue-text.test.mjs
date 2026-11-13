import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';
import { issueText } from '../src/caseSpecIssue.ts';

const BACKEND_MESSAGE = 'CaseSpec validation rejected this field.';
const issue = (code, extra = {}) => ({ code, field: 'flowpaths.0.label', message: BACKEND_MESSAGE, guidance: 'English guidance.', ...extra });

test('a reserved label names the reason in Korean and in English, with the field path', () => {
  const koText = issueText(issue('reserved_label'), 'ko', '정보 없음');
  assert.match(koText, /BOTTOM은 OLGA가 시작할 때 멈추는 예약 이름입니다\. 다른 이름\(예: LOOP_BOTTOM\)을 쓰세요\./);
  assert.match(koText, /flowpaths\.0\.label/);
  const enText = issueText(issue('reserved_label'), 'en', 'n/a');
  assert.match(enText, /BOTTOM/);
  assert.match(enText, /LOOP_BOTTOM/);
  assert.match(enText, /flowpaths\.0\.label/);
});

test('the generic backend sentence never reaches the card for a known code', () => {
  for (const code of ['flowpath_needs_two_sections', 'invalid_topology', 'invalid_geometry']) {
    for (const locale of ['ko', 'en']) {
      const text = issueText(issue(code), locale, '-');
      assert.doesNotMatch(text, /rejected this field/, `${code}/${locale}`);
      assert.notEqual(text, 'English guidance.', `${code}/${locale} has its own copy`);
    }
  }
  assert.match(issueText(issue('flowpath_needs_two_sections'), 'ko', '-'), /구간/);
});

test('an unknown code falls back to guidance, then message, then code, then the missing label', () => {
  assert.match(issueText(issue('brand_new_code'), 'ko', '-'), /^English guidance\./);
  assert.equal(issueText({ code: 'brand_new_code', message: 'Plain message.' }, 'en', '-'), 'Plain message.');
  assert.equal(issueText({ code: 'brand_new_code' }, 'en', '-'), 'brand_new_code');
  assert.equal(issueText({}, 'en', 'n/a'), 'n/a');
  assert.equal(issueText('raw text', 'en', 'n/a'), 'raw text');
  assert.equal(issueText(null, 'ko', '정보 없음'), '정보 없음');
});

test('a PVT range issue shows its own message (node, value, margin), not the generic guidance', () => {
  const message = 'Near the PVT table edge: node OUTLET pressure 0.6 bar is within 0.25 bar of the table minimum 0.5 bar. 표 경계 근처: 노드 OUTLET의 압력 0.6 bar가 표 최소값 0.5 bar에서 0.25 bar 이내에 있습니다.';
  for (const code of ['pvt_range_near_edge', 'pvt_range_outside']) {
    for (const locale of ['ko', 'en']) {
      const text = issueText({ code, field: 'spec', message, guidance: 'Transients may leave the table; widen the grid.' }, locale, '-');
      assert.match(text, /OUTLET/, `${code}/${locale} names the node`);
      assert.match(text, /0\.25 bar/, `${code}/${locale} names the margin`);
      assert.doesNotMatch(text, /^Transients may leave/, `${code}/${locale} is not the generic guidance`);
    }
  }
});

test('every pvt_range code the backend emits is routed to its message', async () => {
  const source = await readFile(new URL('../../src/olga_companion/pvt_range.py', import.meta.url), 'utf8');
  const codes = new Set([...source.matchAll(/"(pvt_range_[a-z_]+)"/g)].map((m) => m[1]));
  assert.ok(codes.size >= 2, `collected ${codes.size} pvt codes`);
  for (const code of codes) {
    assert.equal(issueText({ code, message: 'Specific.', guidance: 'Generic.' }, 'ko', '-'), 'Specific.', code);
  }
});

test('the default field "spec" is not echoed', () => {
  const text = issueText(issue('invalid_spec', { field: 'spec' }), 'en', '-');
  assert.doesNotMatch(text, /spec\)/);
});

test('every code the backend can emit has Korean and English copy', async () => {
  const source = await readFile(new URL('../../src/olga_companion/case_spec_validation.py', import.meta.url), 'utf8');
  const codes = new Set();
  for (const m of source.matchAll(/"code": "([a-z0-9_]+)"/g)) codes.add(m[1]);
  const explicit = source.match(/explicit = \{([\s\S]*?)\n    \}/);
  assert.ok(explicit, 'found the explicit code set');
  for (const m of explicit[1].matchAll(/"([a-z0-9_]+)"/g)) codes.add(m[1]);
  const tail = source.slice(source.indexOf('def _issue_code'));
  for (const m of tail.matchAll(/return "([a-z0-9_]+)"/g)) codes.add(m[1]);
  assert.ok(codes.size > 25, `collected ${codes.size} codes`);
  for (const code of codes) {
    assert.ok(ko[`casespec.issue.${code}`], `ko copy for ${code}`);
    assert.ok(en[`casespec.issue.${code}`], `en copy for ${code}`);
  }
  assert.doesNotMatch(source, /CaseSpec v2 validation rejected/, 'the backend sentence no longer pins a version');
});

test('every warning code the compile tool adds has Korean and English copy', async () => {
  const source = await readFile(new URL('../../src/olga_companion/agent/tool_read_tools.py', import.meta.url), 'utf8');
  const codes = new Set([...source.matchAll(/"code": "([a-z0-9_]+)"/g)].map((m) => m[1]));
  assert.ok(codes.has('pvt_companion_unverified'), 'collected the companion warning code');
  for (const code of codes) {
    assert.ok(ko[`casespec.issue.${code}`], `ko copy for ${code}`);
    assert.ok(en[`casespec.issue.${code}`], `en copy for ${code}`);
  }
  assert.match(issueText({ code: 'pvt_companion_unverified', field: 'pvt_reference', guidance: 'Verify the contained .tab companion before approved publish.' }, 'ko', '-'), /표/);
});

test('the card renders issues through issueText', async () => {
  const card = await readFile(new URL('../src/CaseSpecEvidence.tsx', import.meta.url), 'utf8');
  assert.match(card, /issueText\(/);
  assert.doesNotMatch(card, /item\?\.message \?\? item\?\.code/);
});
